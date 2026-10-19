#!/usr/bin/env python3
"""The pure part of ponos, under assertions.

    python3 tests/run.py

No framework and no dependency, for the same reason the runner has none: a test
suite that needs an install is a test suite that stops being run. Everything
here is pure — nothing touches Notion, git, the network or the disk beyond a
temporary file.

What is covered is what has already gone wrong once, or would go wrong silently:
identifiers that collide, a status name that does not exist, markdown that
reaches Notion as a wall of text, a summary that keeps its verdict.
"""

from __future__ import annotations

import ast
import gzip
import http.client
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import contextlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ponos import config as C  # noqa: E402
from ponos import agents, channels, conversation, credits, kinds, markdown, naming, notion  # noqa: E402
from ponos import notify, openrouter, progress, projects, prompt, provision, question  # noqa: E402
from ponos import schedules, session, state, store, subtypes, sync, systemd  # noqa: E402
from ponos import db, files, images, journal, project_settings, vault  # noqa: E402
from ponos.channels import slack as slack_channel, telegram as telegram_channel  # noqa: E402
from ponos import legacy, models, update, voice, workspace  # noqa: E402
from ponos import ticket as ticket_module  # noqa: E402
from ponos import priority, redaction, worktime  # noqa: E402
from ponos.runner import Runner  # noqa: E402
from ponos import __version__  # noqa: E402
from ponos.__main__ import _names, banner, subcommands, welcome  # noqa: E402
from ponos.__main__ import main as cli_main  # noqa: E402
from ponos.__main__ import build_parser  # noqa: E402
from ponos.web import api as web_api  # noqa: E402
from ponos.web import board as web_board  # noqa: E402
from ponos.web import removal as web_removal  # noqa: E402
from ponos.web import creation as web_creation  # noqa: E402
from ponos.web import attachments as web_attachments  # noqa: E402
from ponos.web import console as web_console  # noqa: E402
from ponos.web import settings as web_settings  # noqa: E402
from ponos.web import live as web_live  # noqa: E402
from ponos.web import statistics as web_statistics  # noqa: E402
from ponos.web import ideas as web_ideas  # noqa: E402
from ponos import ideas  # noqa: E402
from ponos import git as git_module, github_app  # noqa: E402
from ponos.web import github as web_github  # noqa: E402
from ponos.ticket import short_id, slugify  # noqa: E402
from ponos.projects import _normalise  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import release  # noqa: E402

CASES = []


def case(function):
    CASES.append(function)
    return function


# -- identifiers -------------------------------------------------------------


@case
def short_ids_tell_same_day_tickets_apart():
    """Notion IDs are time-ordered, so same-day tickets share a long prefix.

    Two real tickets, created minutes apart, collided on their first eight
    characters — and would have shared one scratch directory.
    """
    a = "3ca451680af480ae9443de0b65d9abf8"
    b = "3ca451680af480beb02ac9d2cb79078c"
    assert a[:8] == b[:8], "premise: these two really do share a prefix"
    assert short_id(a) != short_id(b)
    assert short_id("3ca45168-0af4-80ae-9443-de0b65d9abf8") == short_id(a)
    assert len(short_id(a)) == 8


@case
def a_log_is_found_however_its_id_was_pasted():
    b = "3ca451680af480beb02ac9d2cb79078c"
    name = f"20260828-112441-{short_id(b)}.jsonl"
    assert _names(b, name)
    assert _names("3ca45168-0af4-80be-b02a-c9d2cb79078c", name)
    assert _names("https://www.notion.so/Ticket-" + b, name)
    assert _names(short_id(b), name)
    assert not _names("3ca451680af480ae9443de0b65d9abf8", name), "a neighbour must not match"


@case
def slugs_survive_accents_and_emptiness():
    assert slugify("Supprimer la description") == "supprimer-la-description"
    assert slugify("Corriger l'entête « à faire »") == "corriger-l-entete-a-faire"
    assert slugify("") == "ticket"
    assert len(slugify("x" * 200)) <= 40


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
        from ponos import git as git_module

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
        for folder, remote in remotes.items():
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
        resolver, asked,
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
        resolver, asked,
    ):
        client = _ProjectClient(
            "Jeu d'usine mobile",
            Path=str(resolver._root / "factory-mobile"),  # noqa: SLF001
            Repository="https://github.com/SalvadorCardona/mobile-factory",
        )
        project = resolver.resolve(client, "p-1")
    assert project.is_code and project.path.name == "mobile-factory"
    assert project.is_stale, "found, but not by the declaration that should have found it"
    assert "factory-mobile, from the project's Path property, is not a git repository" in project.note
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
    assert "salvadorcardona/factory-mobile, from the project's Repository property, matches no origin remote" in message
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
        resolver, asked,
    ):
        client = _ProjectClient("Jeu", Repository="https://github.com/SalvadorCardona/factory-mobile")
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
        client = _ProjectClient("Trader IA", Repository="https://github.com/SalvadorCardona/trader-ia")
        project = resolver.resolve(client, "p-1", clone=True)
        root = resolver._root  # noqa: SLF001
    assert project.is_code and project.path == root / "trader-ia"
    assert cloned == [("SalvadorCardona/trader-ia", root / "trader-ia")], "under the name GitHub uses"
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


# -- configuration -----------------------------------------------------------


def _config(body: str) -> C.Config:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n' + body)
    # Written the way a file used to be, and read the way a launch leaves it:
    # its secrets moved into secrets.env.
    C.move_secrets(path)
    return C.load(path)


@case
def a_database_reference_is_normalised_but_a_name_is_not():
    assert C._database_id(
        "https://www.notion.so/w/Master-Tickets-3c3451680af480f5b1aad0785c0322b4?v=1"
    ) == "3c3451680af480f5b1aad0785c0322b4"
    assert C._database_id("3c345168-0af4-80f5-b1aa-d0785c0322b4") == "3c3451680af480f5b1aad0785c0322b4"
    # Not an identifier: handed back untouched, to be looked up by name.
    assert C._database_id("Master Tickets") == "Master Tickets"
    assert C.is_identifier("3c3451680af480f5b1aad0785c0322b4")
    assert not C.is_identifier("Master Tickets")


@case
def blocked_falls_back_on_failed_but_only_when_unset():
    config = _config('[notion.status]\nfailed = "Blocked"\n')
    assert config.notion.state("blocked") == "Blocked"
    assert config.notion.state("ready") == "Ready", "defaults survive a partial block"

    config = _config('[notion.status]\nfailed = "Draft"\nblocked = "Blocked"\n')
    assert config.notion.state("failed") == "Draft"
    assert config.notion.state("blocked") == "Blocked"

    config = _config("")
    assert config.notion.state("review") == "In review"
    assert config.notion.state("done") == "Done"
    assert config.notion.state("blocked") == "Blocked", "its own column, not the failure one"
    assert config.notion.state("failed") == "Failed"


@case
def review_falls_back_on_done_but_only_when_done_is_named():
    """A file that names `done` and not `review` has one column for both.

    Which is also what turns the merge watch off: there is no column for a
    ticket to wait in, so there is nothing to watch. A file that names neither
    gets the defaults, which are two — an open pull request and a merged one
    are not the same day.
    """
    config = _config('[notion.status]\ndone = "Shipped"\n')
    assert config.notion.state("review") == config.notion.state("done") == "Shipped"

    config = _config("")
    assert config.notion.state("review") == "In review"
    assert config.notion.state("done") == "Done", "the defaults keep them apart"

    config = _config('[notion.status]\nreview = "Waiting on you"\ndone = "Shipped"\n')
    assert config.notion.state("review") == "Waiting on you"
    assert config.notion.state("done") == "Shipped"


@case
def a_merge_method_gh_would_refuse_never_reaches_it():
    """The typo is caught here, not by GitHub refusing the merge you watched."""
    assert _config("").runner.merge_method == "squash"
    assert _config('[runner]\nmerge_method = "rebase"\n').runner.merge_method == "rebase"
    assert _config('[runner]\nmerge_method = "MERGE"\n').runner.merge_method == "merge"
    assert _config('[runner]\nmerge_method = "fast-forward"\n').runner.merge_method == "squash"

    from ponos import git as git_module

    assert set(git_module.MERGE_FLAGS) == set(C.MERGE_METHODS)


@case
def force_validated_is_off_for_every_type_until_the_file_says_otherwise():
    """Nothing is merged or published unread by a file that never mentioned it.

    One switch per type, each read on its own, and an empty type — a ticket the
    runner ran by what its project holds — is never one of them.
    """
    quiet = _config("").runner
    assert not any(quiet.forces_validation(kind) for kind in ("code", "writing",
                                                              "external", "publication", ""))
    runner = _config(
        "[runner]\nforce_validated_code = true\nforce_validated_publication = true\n"
    ).runner
    assert runner.forces_validation("code") and runner.forces_validation("publication")
    assert not runner.forces_validation("writing")
    assert not runner.forces_validation("external")
    assert not runner.forces_validation("")

    # And the console can tick them, one box per type, where it saves them.
    path, config = _saved()
    for kind in ("code", "writing", "external", "publication"):
        field = web_settings.FIELDS[f"runner.force_validated_{kind}"]
        assert field.kind == "bool", field
    web_settings.save(config, {"settings": {"runner.force_validated_code": True}})
    assert C.load(path).runner.forces_validation("code")
    web_settings.save(config, {"settings": {"runner.force_validated_code": None}})
    assert not C.load(path).runner.forces_validation("code")


@case
def a_project_with_its_own_validation_overrides_the_file_both_ways():
    """The project's switches when it has them, the file's otherwise.

    A project without its own is the board as it was; one with its own is
    taken at its word, even against the file — on where the file is off, off
    where the file is on. And a database that cannot be read validates nothing.
    """
    eager = _config("[runner]\nforce_validated_code = true\n")
    quiet = _config("")
    page = "1234abcd-0000-0000-0000-00000000beef"
    with _state():
        try:
            assert project_settings.validation(page) is None
            assert project_settings.forced_validation(eager, "code", page) == "global"
            assert project_settings.forced_validation(quiet, "code", page) == ""
            assert project_settings.forced_validation(eager, "", page) == ""

            # Off on the project, on in the file: the project wins.
            project_settings.set_validation(page, "Client", {"code": False, "publication": True})
            assert project_settings.forced_validation(eager, "code", page) == ""
            assert project_settings.forced_validation(eager, "publication", page) == "project"
            # On on the project, off in the file: the project wins again.
            project_settings.set_validation(page, "Client", {"code": True})
            assert project_settings.forced_validation(quiet, "code", page) == "project"
            assert project_settings.forced_validation(quiet, "publication", page) == ""
            # Another project, and a project without a page, still follow the file.
            assert project_settings.forced_validation(eager, "code", "f" * 32) == "global"
            assert project_settings.forced_validation(eager, "code", "") == "global"

            # Keyed by the page whichever way its id is spelled, and kept across
            # a restart: the connection closed, the file opened again.
            db.close()
            assert project_settings.validation(page.replace("-", "").upper()) == {
                "code": True, "writing": False, "external": False, "publication": False,
            }
            assert project_settings.owning_validation() == [
                {"id": page.replace("-", ""), "name": "Client"}
            ]

            # Handed back to the file: the row goes, and the file decides again.
            project_settings.set_validation(page, "Client", None)
            assert project_settings.validation(page) is None
            assert project_settings.owning_validation() == []
            assert project_settings.forced_validation(eager, "code", page) == "global"

            # A database that cannot be read is never a merge nobody read.
            original = project_settings.validation

            def broken(project: str) -> None:
                raise db.DatabaseError("locked")

            project_settings.validation = broken
            try:
                assert project_settings.forced_validation(eager, "code", page) == ""
            finally:
                project_settings.validation = original
        finally:
            db.close()


@case
def the_validation_line_says_whose_decision_it_was():
    """A report that only said "validated" would not say which switch to turn off."""
    english, french = voice.Voice("en"), voice.Voice("fr")
    line = english.say(
        "forced-validation", kind="Code", source=english.say("forced-by-project")
    )
    assert line == "Validated automatically (Force validated: Code) — the project's setting"
    assert french.say("forced-by-global") == "réglage global"
    assert french.say("forced-by-project") == "réglage du projet"


@case
def a_project_page_reads_and_saves_its_own_automatic_validation():
    """The tab's two calls: what applies, and the project's own switches saved.

    The switches are worded as the global card words them — the same fields —
    and turning them on starts from the file's values, which `values` already
    carries while the project has none of its own.
    """
    with _state(), _board() as board:
        try:
            page = board.create_row("projects", "Perso", {})
            api = _markdown_api(board)
            api._config.runner.force_validated_publication = True
            read = api.project_settings(page)
            validation = read["validation"]
            assert validation["own"] is False
            assert validation["global"]["publication"] is True
            assert validation["values"] == validation["global"]
            section = next(item for item in web_settings.SECTIONS if item.key == "validation")
            assert [field["label"] for field in validation["fields"]] == [
                field.label for field in section.fields
            ]
            assert [field["kind"] for field in validation["fields"]] == [
                "code", "publication", "writing", "external",
            ]

            saved = api.save_project_settings(
                page, {"validation": {"own": True, "values": {"code": True, "publication": False}}}
            )
            assert saved["validation"]["own"] is True
            assert saved["validation"]["values"]["code"] is True
            assert saved["validation"]["values"]["publication"] is False
            assert saved["validation"]["global"]["publication"] is True
            assert project_settings.owning_validation() == [
                {"id": project_settings.key(page), "name": "Perso"}
            ]

            for wrong in ({}, {"validation": {"own": "yes"}},
                          {"validation": {"own": True, "values": {"deploy": True}}},
                          {"validation": {"own": True, "values": {"code": "on"}}}):
                try:
                    api.save_project_settings(page, wrong)
                except ValueError:
                    continue
                raise AssertionError(f"{wrong} should have been refused")

            back = api.save_project_settings(page, {"validation": {"own": False}})
            assert back["validation"]["own"] is False
            assert back["validation"]["values"] == back["validation"]["global"]
            assert project_settings.owning_validation() == []
        finally:
            db.close()


@case
def the_interval_never_reaches_systemd_as_zero():
    assert _config("[runner]\ninterval_seconds = 0\n").runner.interval_seconds == 1
    assert _config("[runner]\ninterval_seconds = 10\n").runner.interval_seconds == 10
    assert _config("").runner.interval_seconds == 1800


@case
def the_update_check_never_runs_more_than_once_a_minute():
    """At a ten-second cadence, an unbounded value would fetch six times a minute."""
    assert _config("").runner.update_interval_seconds == 3600
    assert _config("[runner]\nupdate_interval_seconds = 5\n").runner.update_interval_seconds == 60
    assert _config("").runner.auto_update is True
    assert _config("[runner]\nauto_update = false\n").runner.auto_update is False


@case
def optional_properties_have_names_even_when_absent():
    config = _config("")
    for key in ("status", "project", "agent", "pull_request", "session", "model",
                "priority", "cost", "duration"):
        assert config.notion.prop(key), key


@case
def a_workspace_is_named_once_and_the_rest_is_found():
    config = _config("")
    assert config.notion.page("tickets") == "Tickets"
    assert config.notion.page("context") == "Context"
    renamed = _config('[notion.pages]\ncontext = "Qui je suis"\n')
    assert renamed.notion.page("context") == "Qui je suis"
    assert renamed.notion.page("tickets") == "Tickets", "defaults survive a partial block"


@case
def a_workspace_alone_is_enough_to_run():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntoken = "ntn_real"\n'
        'workspace = "https://www.notion.so/w/3a8451680af480918afcf0eb9cf70e7b?v=1"\n'
    )
    C.move_secrets(path)
    config = C.load(path)
    assert config.notion.workspace == "3a8451680af480918afcf0eb9cf70e7b", "URL reduced to an ID"
    assert not config.notion.tickets_database
    config.require_usable()  # neither raises nor needs a tickets database


@case
def neither_a_workspace_nor_a_database_is_refused():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\n')
    try:
        C.load(path).require_usable()
    except C.ConfigError as error:
        assert "notion.workspace" in str(error)
    else:
        raise AssertionError("a configuration naming no tickets database must be refused")


# -- every other model --------------------------------------------------------


@case
def no_openrouter_key_starts_a_session_exactly_as_before():
    """The one thing an unconfigured key must cost: nothing at all."""
    config = _config("")
    assert config.openrouter.key == ""
    assert config.openrouter.route_sessions is False
    assert openrouter.environment(config.openrouter) == {}
    # And a key can be there without anything about the runner changing.
    keyed = _config('[openrouter]\nkey = "sk-or-v1-secret"\n')
    assert openrouter.environment(keyed.openrouter) == {
        "OPENROUTER_API_KEY": "sk-or-v1-secret",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }


@case
def a_routed_session_is_told_where_to_go_and_with_what():
    """`ANTHROPIC_AUTH_TOKEN`, not `ANTHROPIC_API_KEY`: a gateway wants a bearer."""
    config = _config('[openrouter]\nkey = "sk-or-v1-secret"\nroute_sessions = true\n')
    variables = openrouter.environment(config.openrouter)
    assert variables["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert variables["ANTHROPIC_AUTH_TOKEN"] == "sk-or-v1-secret"
    assert "ANTHROPIC_API_KEY" not in variables
    # A gateway of your own, and the trailing slash that would double up.
    own = _config(
        '[openrouter]\nkey = "k"\nroute_sessions = true\nbase_url = "https://gw.example/v1/"\n'
    )
    assert openrouter.environment(own.openrouter)["ANTHROPIC_BASE_URL"] == "https://gw.example/v1"
    blank = _config('[openrouter]\nkey = "k"\nbase_url = ""\n')
    assert blank.openrouter.base_url == C.OPENROUTER_URL, "emptied, the default answers"


@case
def what_the_runner_adds_wins_over_the_shell_it_was_started_from():
    """A key configured for the runner beats one that happens to be exported."""
    seen: dict[str, str] = {}

    class _Process:
        stdin = io.StringIO()
        stdout: list[str] = []
        returncode = 0

        def wait(self) -> None:
            pass

    def _popen(command, **arguments):
        seen.update(arguments["env"])
        return _Process()

    directory = Path(tempfile.mkdtemp())
    original = (session.available, subprocess.Popen)
    session.available = lambda: "/usr/bin/claude"
    subprocess.Popen = _popen
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-shell"
    try:
        session.run(
            "hello",
            cwd=directory,
            log=directory / "run.jsonl",
            environment={"OPENROUTER_API_KEY": "sk-or-v1-configured"},
        )
    finally:
        session.available, subprocess.Popen = original
        os.environ.pop("OPENROUTER_API_KEY", None)
    assert seen["OPENROUTER_API_KEY"] == "sk-or-v1-configured"
    assert seen["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


# -- the workspace -----------------------------------------------------------


class _FakeClient:
    """Just enough Notion to resolve a workspace, and nothing that reaches out."""

    def __init__(self, rows: dict[str, str], text: str = "", broken: set[str] = frozenset()):
        self._rows = rows
        self._text = text
        self._broken = broken

    def resolve_database(self, identifier: str) -> str:
        if identifier in self._broken:
            raise notion.NotionError(f"{identifier}: object not found")
        return f"db-of-{identifier}"

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        return [notion.Page(id=page, url="", title=title) for title, page in self._rows.items()]

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        if page_id in self._broken:
            raise notion.NotionError(f"{page_id}: object not found")
        return self._text


def _settings(**overrides) -> C.Notion:
    values = {"token": "ntn_real", "workspace": "space", "pages": {}}
    values.update(overrides)
    return C.Notion(**values)


@case
def the_rows_of_a_workspace_become_the_runners_databases():
    client = _FakeClient(
        {"Tickets": "p-tickets", "Projects": "p-projects", "Context": "p-context"},
        text="Je suis Camille Martin.",
    )
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "Je suis Camille Martin."
    assert not space.warnings


@case
def a_row_is_found_however_its_title_is_capitalised():
    client = _FakeClient({"tickets": "p-tickets", "CONTEXT": "p-context"}, text="x")
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "x"


@case
def a_board_built_before_the_names_were_settled_still_resolves():
    """The rows shipped as "Master Tickets" and "Soul" before those names settled.

    Renaming four rows by hand is not a migration anyone should be asked to run,
    so the old titles are tried after the current ones — and only while the
    configuration itself names none, since a title someone typed is a title
    they meant.
    """
    client = _FakeClient(
        {"Master Tickets": "p-tickets", "Master project": "p-projects", "Soul": "p-soul"},
        text="who I am",
    )
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "who I am"
    assert not space.warnings

    # The new names win when a board carries both, rather than the older row.
    both = _FakeClient({"Tickets": "p-new", "Master Tickets": "p-old"})
    assert workspace.from_notion(both, _settings()).tickets == "db-of-p-new"

    # And a configuration that names a row is never second-guessed.
    named = _settings(pages={"tickets": "Backlog"})
    try:
        workspace.from_notion(_FakeClient({"Master Tickets": "p-old"}), named)
    except notion.NotionError as error:
        assert "Backlog" in str(error)
    else:
        raise AssertionError("a named row must not fall back on a legacy title")


@case
def a_missing_context_page_warns_but_never_fails_a_run():
    client = _FakeClient({"Tickets": "p-tickets"})
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "" and space.projects == ""
    assert any("Context" in warning for warning in space.warnings)

    # Present but unreadable, and present but empty, are both worth saying too.
    unreadable = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, broken={"p-context"})
    assert any("unreadable" in warning for warning in workspace.from_notion(unreadable, _settings()).warnings)
    empty = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, text="   ")
    assert any("empty" in warning for warning in workspace.from_notion(empty, _settings()).warnings)


@case
def a_missing_tickets_page_is_the_one_thing_that_fails():
    client = _FakeClient({"Context": "p-context", "Projects": "p-projects"})
    try:
        workspace.from_notion(client, _settings())
    except notion.NotionError as error:
        assert "Tickets" in str(error)
        assert "Context" in str(error), "the message lists what was actually found"
    else:
        raise AssertionError("a workspace without a tickets page must not resolve")


@case
def an_explicit_database_still_wins_over_the_workspace():
    client = _FakeClient({"Tickets": "p-tickets"})
    space = workspace.from_notion(client, _settings(tickets_database="chosen"))
    assert space.tickets == "db-of-chosen"

    # And a configuration written before workspaces existed resolves the same.
    legacy = workspace.from_notion(client, _settings(workspace="", tickets_database="chosen"))
    assert legacy.tickets == "db-of-chosen"
    assert legacy.rows == {} and not legacy.warnings


# -- provisioning ------------------------------------------------------------


class _Board:
    """A Notion that remembers what was created, without a network in sight."""

    def __init__(self, databases=None, rows=None, schemas=None, text=""):
        self._databases = databases or {}          # page id -> {title: db id}
        self._rows = rows or {}                    # db id -> {title: page id}
        self._schemas = schemas or {}              # db id -> {name: {shape}}
        self._text = text
        self.created = []
        self.patched = []
        self.appended = []

    # reading
    def child_databases(self, page_id):
        return dict(self._databases.get(page_id, {}))

    def schema(self, database_id):
        return {name: next(iter(shape)) for name, shape in self._schemas.get(database_id, {}).items()}

    def database(self, database_id):
        return {"properties": {
            name: {"type": next(iter(shape)), **shape}
            for name, shape in self._schemas.get(database_id, {}).items()
        }}

    def query(self, database_id, filter_=None):
        return [
            notion.Page(id=page, url="", title=title)
            for title, page in self._rows.get(database_id, {}).items()
        ]

    def blocks_text(self, page_id, depth=0, *, live=True):
        return self._text

    # writing
    def create_database(self, parent_page_id, title, properties, *, inline=True):
        identifier = f"db-{title.lower().replace(' ', '-')}"
        self._databases.setdefault(parent_page_id, {})[title] = identifier
        self._schemas[identifier] = dict(properties)
        self._rows.setdefault(identifier, {})
        self.created.append(identifier)
        return identifier

    def add_properties(self, database_id, properties):
        self._schemas.setdefault(database_id, {}).update(properties)
        self.patched.append((database_id, sorted(properties)))

    def create_row(self, database_id, title, values=None):
        page = f"page-{title.lower().replace(' ', '-')}"
        self._rows.setdefault(database_id, {})[title] = page
        self.created.append(page)
        return page

    def append_markdown(self, page_id, markdown):
        # A page that has just been written to is no longer empty — which is
        # what stops the second `init` from seeding the context page again.
        self.appended.append(page_id)
        self._text = markdown
        return 1


@case
def a_bare_page_becomes_the_whole_board():
    board = _Board()
    report = provision.provision(board, _settings(), "root")

    assert report.workspace == "db-ponos"
    assert report.tickets == "db-tickets"
    rows = board._rows["db-ponos"]
    assert set(rows) == {"Tickets", "Projects", "Agents", "Context", "Schedules"}

    schema = board._schemas["db-tickets"]
    for expected in ("Status", "Project", "Agent", "Runner", "Session", "Scheduled"):
        assert expected in schema, expected

    # The relations point at databases that existed before the tickets did.
    assert schema["Project"]["relation"]["database_id"] == "db-projects"
    assert schema["Agent"]["relation"]["database_id"] == "db-agents"
    # …and are spelled the way the API accepts: the kind is named *and* given
    # its empty object, or the request is rejected as `undefined`.
    for name in ("Project", "Agent"):
        assert schema[name]["relation"]["type"] == "single_property"
        assert schema[name]["relation"]["single_property"] == {}

    # A status property cannot be created through the API; a select can, and the
    # runner reads both. Every column must be there, validated included.
    options = [option["name"] for option in schema["Status"]["select"]["options"]]
    assert options == [
        "Ready", "In progress", "In review", "Validated", "Done", "Failed", "Blocked", "Cancelled",
    ]
    # And the credit is not one of them: a ticket nothing was started for has not
    # moved, so it is ticked where it stands rather than sent to an eighth column.
    assert schema["Waiting for credit"] == {"checkbox": {}}

    assert board.appended, "the context page is seeded rather than left blank"


@case
def running_init_twice_changes_nothing():
    board = _Board()
    provision.provision(board, _settings(), "root")
    before = dict(board._schemas["db-tickets"])
    board.created.clear()

    second = provision.provision(board, _settings(), "root")
    assert board.created == [], "nothing is created a second time"
    assert board._schemas["db-tickets"] == before
    assert second.tickets == "db-tickets"
    assert all(verb == "kept" for verb, _ in second.steps), second.steps


@case
def init_completes_a_board_that_predates_a_column():
    """The second reason this command exists: adding what a version did not have.

    A board built before `Scheduled` gets the column rather than a line in a
    changelog telling its owner to add it by hand.
    """
    board = _Board(
        databases={"root": {"ponos": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Status": {"select": {"options": [
            {"name": "Ready", "color": "blue"}, {"name": "Mine", "color": "purple"},
        ]}}}},
    )
    provision.provision(board, _settings(), "root")

    schema = board._schemas["db-tickets"]
    assert "Scheduled" in schema and "Cost" in schema

    # Options are merged, never replaced: a column somebody added is still there.
    options = [option["name"] for option in schema["Status"]["select"]["options"]]
    assert "Mine" in options and "Blocked" in options
    assert options.index("Mine") < options.index("Blocked"), "what exists keeps its place"


@case
def a_real_status_column_is_reported_rather_than_patched():
    """The one thing the API cannot do, said out loud instead of discovered late.

    A `status` property built in Notion's own interface accepts no new options
    from the API. Silence here would surface as a ticket failing to be marked
    "Blocked", weeks later, at the end of a session.
    """
    board = _Board(
        databases={"root": {"ponos": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Status": {"status": {"options": [
            {"name": "Ready"}, {"name": "In progress"},
        ]}}}},
    )
    report = provision.provision(board, _settings(), "root")

    assert not any(name == "Status" for _, names in board.patched for name in names)
    told = [what for verb, what in report.steps if verb == "by hand"]
    assert told and "In review" in told[0] and "Blocked" in told[0], told
    assert "Ready" not in told[0], "only what is actually missing"


@case
def a_column_someone_retyped_is_left_alone():
    board = _Board(
        databases={"root": {"ponos": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Cost": {"rich_text": {}}}},
    )
    provision.provision(board, _settings(), "root")
    assert board._schemas["db-tickets"]["Cost"] == {"rich_text": {}}, "not overruled"


@case
def two_states_on_one_column_produce_one_option():
    """Notion refuses a select that lists the same option twice."""
    settings = _settings()
    settings.status = {"failed": "Needs you", "blocked": "Needs you"}
    names = [option["name"] for option in provision.status_options(settings)]
    assert names.count("Needs you") == 1
    # Seven: the two that were merged count once, and renaming a failure column
    # says nothing about the validated one, nor the cancelled one, which keep
    # their defaults.
    assert len(names) == 7 and "Validated" in names and "Cancelled" in names

    settings.status = {"review": "Done", "done": "Done"}
    names = [option["name"] for option in provision.status_options(settings)]
    assert names.count("Done") == 1
    assert "Validated" not in names, "a board that ends at the pull request has no gesture"


@case
def the_workspace_is_written_back_into_the_configuration():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\n# keep me\ntoken = "ntn_x"\nworkspace = ""\n\n[runner]\nfetch = true\n')

    assert C.write_notion_value(path, "workspace", "abc") is True
    assert C.write_notion_value(path, "workspace", "abc") is False, "already says that"

    text = path.read_text()
    assert 'workspace = "abc"' in text
    assert "# keep me" in text, "a hand-edited file keeps its comments"
    assert "[runner]\nfetch = true" in text, "other tables are untouched"
    assert C.load(path).notion.workspace == "abc"


# -- the prompt --------------------------------------------------------------


@case
def the_prompt_reads_from_the_widest_frame_to_the_narrowest():
    text = prompt.build(
        prompt.DEFAULT,
        project="Animalink",
        title="Retirer l'entête",
        body="Le header prend trop de place.",
        repo="/home/x/animalink",
        branch="ticket/x",
        base="main",
        url="https://notion.so/x",
        brief="Ton: direct, pas d'emoji.",
        context="Je suis Camille Martin, développeur web.",
    )
    assert text.index("Camille Martin") < text.index("Ton: direct"), "the global frame comes first"
    assert text.index("Ton: direct") < text.index("# Context"), "then the project, then the mechanics"
    assert "Le header prend trop de place." in text


@case
def a_workspace_without_a_context_page_changes_nothing():
    common = dict(
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    bare = prompt.build(prompt.DEFAULT, **common)
    assert "# Who you are working for" not in bare
    assert prompt.build(prompt.DOCUMENT, **common, context="   ") == prompt.build(
        prompt.DOCUMENT, **common
    ), "whitespace is not a context"


# -- the language it answers in ----------------------------------------------


@case
def a_language_is_read_down_to_one_the_runner_speaks():
    """A locale, a capital, a language written out: all one answer."""
    for spelling in ("fr", "FR", "fr-FR", "fr_CA", " Français ", "french"):
        assert voice.understood(spelling) == "fr", spelling
    for spelling in ("en", "English", "en-GB", "anglais"):
        assert voice.understood(spelling) == "en", spelling
    # Not a failure: a typo in a language name must not be the reason a ticket
    # comes back unreported.
    assert voice.understood("") == voice.understood("klingon") == "en"


@case
def a_runner_nobody_told_a_language_says_exactly_what_it_used_to():
    """Empty is not “English”: it is “nobody decided”, and the prompts say so.

    Every template already carries its own rule — write in the language of the
    ticket, of the message — and a default that overrode it would answer a
    French ticket in English on the day this shipped.
    """
    common = dict(
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    assert prompt.build(prompt.DEFAULT, **common) == prompt.build(
        prompt.DEFAULT, **common, language=voice.Voice().instruction()
    )
    assert voice.Voice("").instruction() == ""
    assert voice.Voice("en").instruction(), "asking for English is still asking"

    asked = prompt.build(prompt.DEFAULT, **common, language=voice.Voice("fr").instruction())
    assert "Write in French" in asked
    assert asked.index("Write in French") < asked.index("End with a final line")
    assert "commit messages" in asked, "and the repository keeps its own language"


@case
def a_conversation_is_told_the_language_too_and_so_is_its_next_turn():
    """A thread that answers in French once and in English after is worse than
    a thread that never switched."""
    said = voice.Voice("fr")
    first = prompt.conversation(
        prompt.CONVERSATION,
        project="Animalink", title="t", body="b", where="w", url="u", message="et le footer ?",
        language=said.instruction(reply=True),
    )
    assert "Answer in French" in first
    assert "Answer in French" in prompt.follow_up("et le header ?", said.instruction(reply=True))
    assert prompt.follow_up("et le header ?") == prompt.FOLLOW_UP.format(
        message="et le header ?", language=""
    ), "and nothing at all when nothing was asked for"


@case
def a_report_opens_on_what_is_expected_of_you_and_says_it_in_three_lines():
    """The first line is a notification: it has eighty characters, and that is
    the whole of the design.

    Nothing in front of it — the host that used to sign every report spent its
    first forty-four characters saying which laptop was talking — and nothing
    under it but the sentence and the link.
    """
    for language, verdict, expected in (
        ("", "To review", "PR #1 · 3 commits · 18 minutes · $6.41"),
        ("fr", "À relire", "PR #1 · 3 commits · 18 minutes · 6,41 $"),
    ):
        said = voice.Voice(language)
        report = said.report(
            said.verdict(
                "review",
                said.say("pull-request", number="1"),
                said.count(3, "commit"),
                *said.spent(1092.0, 6.405),
            ),
            "Le header est parti.",
            "https://github.com/x/y/pull/1",
        )
        first = report.splitlines()[0]
        assert first == f"✅ {verdict} — {expected}", first
        assert len(first) <= 80, "a phone shows about that much, and then stops"
        assert len(report.splitlines()) == 3
        assert report.endswith("https://github.com/x/y/pull/1")
        assert "ponos@" not in report and "claude --resume" not in report

    assert voice.Voice().spent(90.0, 0.0) == ("2 minutes", ""), "no price, nothing to say"
    assert voice.Voice().verdict("failed") == "⚠️ Failed", "and no facts, no dash"


@case
def a_sentence_a_session_wrote_too_long_is_cut_on_a_word():
    """The prompt asks for one sentence and mostly gets one. Mostly is not a
    length, and a report is not where to find that out."""
    said = voice.Voice()
    assert said.brief("Le header est parti.") == "Le header est parti."
    assert said.brief("  two\n lines  ") == "two lines", "and a paragraph is one line"
    long = "ajoute la commande app:search:diagnose " * 10
    cut = said.brief(long)
    assert len(cut) <= voice.BRIEF and cut.endswith("…")
    assert not cut.rstrip("…").endswith(" "), "cut on a word, not mid-syllable"


@case
def a_report_is_told_from_an_answer_by_the_mark_it_opens_with():
    """Three places used to recognise the runner by the host it signed with, so
    dropping the host without putting something in its place would have had the
    next run read its own words back as an instruction."""
    assert voice.is_report("✅ To review — PR #1 · 2 commits")
    assert voice.is_report("🙋 Bloqué — quel en-tête ?")
    assert not voice.is_report("Celui du dashboard, pas du site public.")
    # A board does not start over when the runner is updated: the reports
    # already on it opened with a host, and are still ours.
    assert voice.is_report(f"{legacy.OLD}@laptop — done.\nFait.")
    assert voice.plain(f"{legacy.OLD}@laptop — done.\nFait.") == "done.\nFait."
    assert voice.plain("✅ To review — PR #1") == "✅ To review — PR #1"


@case
def a_measurement_is_rounded_to_something_a_person_would_say():
    """Nobody reports their afternoon to the tenth of a minute."""
    said = voice.Voice()
    assert said.minutes(1092.0) == "18 minutes"
    assert said.minutes(90.0) == "2 minutes"
    assert said.minutes(20.0) == "under a minute"
    assert voice.Voice("fr").minutes(20.0) == "moins d'une minute"
    assert said.count(1, "commit") == "1 commit" and said.count(3, "commit") == "3 commits"
    assert voice.Voice("fr").count(1, "block") == "1 bloc"


@case
def every_phrase_exists_in_every_language_it_claims_to_speak():
    """A key nobody translated is a sentence that fails the day it is said.

    Which is the whole risk of a table like this: the missing one is always the
    failure path, and the failure path is what nobody exercises before shipping.
    """
    for key, spellings in voice._SAID.items():
        assert set(spellings) == set(voice.LANGUAGES), key
        for language, text in spellings.items():
            assert text.strip(), f"{key}/{language}"
    assert voice.DEFAULT in voice.LANGUAGES


# -- the role a ticket is handled by -----------------------------------------


class _AgentClient:
    def __init__(self, page: notion.Page | None, brief: str = "", broken: bool = False):
        self._page, self._brief, self._broken = page, brief, broken

    def page(self, page_id: str) -> notion.Page:
        if self._page is None:
            raise notion.NotionError("object not found")
        return self._page

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        if self._broken:
            raise notion.NotionError("object not found")
        return self._brief


def _agent_page(title: str, model: str = "") -> notion.Page:
    properties = {"Name": {"type": "title", "title": [{"plain_text": title}]}}
    if model:
        properties["Model"] = {"type": "select", "select": {"name": model}}
    return notion.Page(id="p-agent", url="", title=title, properties=properties)


@case
def an_agent_is_a_page_and_may_name_its_model():
    client = _AgentClient(_agent_page("Rédacteur", "haiku"), brief="Ton direct, pas d'emoji.")
    agent = agents.resolve(client, "p-agent")
    assert agent.name == "Rédacteur"
    assert agent.brief == "Ton direct, pas d'emoji."
    assert agent.model == "haiku"
    assert agent, "a named agent is truthy"


@case
def an_unreadable_agent_is_no_agent_rather_than_a_failed_ticket():
    assert not agents.resolve(_AgentClient(None), "p-agent").name
    # The page reads but its body does not: the role is lost, the run is not.
    partial = agents.resolve(_AgentClient(_agent_page("Rédacteur"), broken=True), "p-agent")
    assert partial.name == "Rédacteur" and partial.brief == ""
    assert not agents.Agent(), "no agent at all is falsy"


# -- the discussion on a ticket ----------------------------------------------


class _CommentClient:
    def __init__(self, texts: list[str], error: str = ""):
        self._texts, self._error = texts, error

    def comments(self, page_id: str) -> list[notion.Comment]:
        if self._error:
            raise notion.NotionError(self._error)
        return [notion.Comment(text) for text in self._texts]


def _bare_runner(client) -> Runner:
    """A Runner with its Notion replaced, and nothing else touched."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = client
    runner.config = _config("")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner._comments = {}
    runner._usage_warned = False
    runner._spellings = conversation.names()
    runner._me = ""          # Notion never said; the signature is all there is
    runner._identity_error = ""
    return runner


def _runner_reading(texts: list[str], error: str = "") -> tuple[Runner, list[str]]:
    runner = _bare_runner(_CommentClient(texts, error))
    ticket = type("T", (), {"page": notion.Page(id="p-ticket", url="", title="t")})()
    return runner, runner.discussion(ticket)


@case
def a_question_a_run_asked_comes_back_with_its_answer():
    _, lines = _runner_reading([
        f"{legacy.OLD}@laptop — blocked.\nThe ticket does not say which header.\n\n"
        "Session: `abc-123` — `claude --resume abc-123`\nLog: /home/x/log.jsonl",
        "Celui du dashboard, pas du site public.",
    ])
    assert lines == [
        "a previous run: blocked. The ticket does not say which header.",
        "the ticket's author: Celui du dashboard, pas du site public.",
    ], lines
    assert "Session:" not in "".join(lines), "the machinery of a past run is not context"


@case
def a_long_discussion_is_cut_from_the_oldest_end():
    _, lines = _runner_reading([f"comment number {index} " + "x" * 300 for index in range(20)])
    assert len(lines) <= 10, "at most the last ten"
    assert sum(len(line) for line in lines) <= 2000
    assert "number 19" in lines[-1], "the newest survives"
    assert "number 0" not in " ".join(lines), "the oldest is what goes"


@case
def comments_the_integration_cannot_read_are_not_a_failure():
    _, lines = _runner_reading([], error="403 API token does not have access")
    assert lines == []


def _answered(texts: list[str], error: str = "", agent: str = "") -> bool:
    """Would a reply on that ticket put it back in the queue?"""
    runner = _bare_runner(_CommentClient(texts, error))
    properties = {}
    if agent:
        properties["Runner"] = {"type": "rich_text", "rich_text": [{"plain_text": agent}]}
    page = notion.Page(id="p-ticket", url="", title="t", properties=properties)
    return runner._answered(type("T", (), {"page": page})())


REPORT = "🙋 Stuck — the ticket does not say which header"
DONE = "✅ To review — PR #1 · 1 commit\nFait."


@case
def answering_a_ticket_the_runner_handled_puts_it_back_in_the_queue():
    """The reply is the whole gesture: nothing to move on the board."""
    assert _answered([REPORT, "Celui du dashboard, pas du site public."])
    # Several rounds, and the answer is still the last word.
    assert _answered([REPORT, "réponse", DONE, "et le footer ?"])


@case
def a_ticket_wakes_only_once_per_answer():
    assert not _answered([REPORT]), "the runner having the last word is not an answer"
    assert not _answered([REPORT, "réponse", DONE]), (
        "the report the next run posts is what closes the ticket again"
    )
    assert not _answered([])


@case
def a_ticket_no_run_of_ours_ever_touched_is_left_alone():
    assert not _answered(["Une question posée avant qu'aucun run n'y touche."])
    # A report no longer says which machine wrote it — the board's own Runner
    # column does, and it is what a second machine reads to leave this alone.
    assert not _answered([DONE, "et pour le footer ?"], agent="ponos@vps"), (
        "a ticket handled by another host is that host's to pick up"
    )
    assert _answered([DONE, "et pour le footer ?"], agent="ponos@laptop")
    assert not _answered([REPORT, "réponse"], error="403 API token does not have access")


@case
def waking_looks_everywhere_but_where_a_status_already_speaks():
    """Done stays done, in review waits on a merge, validated on the runner."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config("")
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    offered: list[str] = []
    runner.client = type("S", (), {
        "schema": lambda self, database: {"Status": "status"},
        "options": lambda self, database, name: offered,
    })()
    excluded = {
        condition["status"]["does_not_equal"] for condition in runner._woken_filter()["and"]
    }
    assert excluded == {"In review", "Validated", "Done", "Ready", "In progress"}
    assert all(condition["property"] == "Status" for condition in runner._woken_filter()["and"])
    # Five names spoken, and everything else — failed, blocked, whatever the
    # board adds later — left in, because that is where an answer is expected.
    # A ticket waiting for credit is not among them: it never left Ready.
    assert len(runner._woken_filter()["and"]) == 5
    # A cancelled ticket is given up on: a comment under it wakes nothing — on
    # a board that offers the option, since Notion refuses a filter on one it
    # does not know.
    offered.append("Cancelled")
    excluded = {
        condition["status"]["does_not_equal"] for condition in runner._woken_filter()["and"]
    }
    assert excluded == {"In review", "Validated", "Done", "Ready", "In progress", "Cancelled"}


# -- talking in the comments -------------------------------------------------

ME = "bot-user-id"


def _said(text: str, *, by: str = "human", thread: str = "d1", ident: str = "") -> notion.Comment:
    return notion.Comment(
        text, id=ident or f"c-{abs(hash((text, thread))) % 10**6}", discussion_id=thread,
        created_by=by,
    )


def _pending(comments: list[notion.Comment], mention: str = "") -> list[conversation.Thread]:
    return conversation.waiting(
        comments, me=ME, spellings=conversation.names(mention, "Ponos")
    )


@case
def comments_are_grouped_into_the_threads_they_belong_to():
    grouped = conversation.threads([
        _said("le rapport", by=ME, thread="d1"),
        _said("une remarque sans rapport", thread="d2"),
        _said("et pourquoi ?", thread="d1"),
    ])
    assert [thread.discussion for thread in grouped] == ["d1", "d2"], "in the order they appear"
    assert len(grouped[0].comments) == 2
    assert grouped[0].last.text == "et pourquoi ?"
    assert grouped[0].spoken_by(ME) and not grouped[1].spoken_by(ME)


@case
def a_comment_with_no_thread_of_its_own_is_not_lumped_with_the_others():
    """Notion answered without a discussion: two remarks are still two remarks."""
    grouped = conversation.threads([
        notion.Comment("une chose", id="c1"),
        notion.Comment("une autre", id="c2"),
    ])
    assert len(grouped) == 2


@case
def replying_under_its_report_is_how_you_talk_to_it():
    pending = _pending([
        _said(f"{legacy.OLD}@laptop — done.\nFait.", by=ME),
        _said("pourquoi ce nom de branche ?"),
    ])
    assert [thread.last.text for thread in pending] == ["pourquoi ce nom de branche ?"]


@case
def naming_it_reaches_it_in_a_thread_it_never_spoke_in():
    """A remark of yours is a remark of yours — until you name it."""
    remark = [_said("il faudra penser à prévenir Marie", thread="d9")]
    assert _pending(remark) == []
    assert len(_pending([_said("@claude tu en penses quoi ?", thread="d9")])) == 1
    # The word is yours to choose, and its own name always works.
    assert len(_pending([_said("@ia une idée ?", thread="d9")], mention="@ia")) == 1
    assert len(_pending([_said("Ponos, une idée ?", thread="d9")])) == 1


@case
def it_never_answers_itself():
    """The one failure mode here that would never stop on its own."""
    conversed = [
        _said(f"{legacy.OLD}@laptop — done.\nFait.", by=ME),
        _said("pourquoi ?"),
        _said("parce que la branche existait déjà.", by=ME),
    ]
    assert _pending(conversed) == [], "we had the last word"
    # And without knowing who we are, nothing is answered at all: our own
    # replies would read as somebody else's questions.
    assert conversation.waiting(conversed, me="", spellings=conversation.names()) == []


@case
def a_question_it_has_already_answered_is_not_answered_twice():
    """Notion hands back a thread whose reply is still in flight."""
    ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    ledger.remember_thread("d1", session="s-1", comment="c-42")
    assert ledger.answered("d1") == "c-42"
    assert ledger.session_of("d1") == "s-1", "the next question resumes the same session"
    ledger.forget_session("d1")
    assert ledger.session_of("d1") == "" and ledger.answered("d1") == "c-42"


@case
def naming_it_asks_for_words_where_a_bare_answer_asks_for_work():
    """The `blocked` loop is untouched; the mention is what opts out of it."""
    report = f"{legacy.OLD}@laptop — blocked.\nQuel en-tête ?"
    assert _answered([report, "celui du dashboard."]), "a plain answer still runs the ticket"
    assert not _answered([report, "@claude pourquoi tu demandes ?"])
    assert not _answered([report, "Ponos, pourquoi tu demandes ?"])


@case
def the_name_is_stripped_from_the_message_but_only_where_it_is_a_salutation():
    spellings = conversation.names("", "Ponos")
    assert conversation.strip_mention("@claude pourquoi ?", spellings) == "pourquoi ?"
    assert conversation.strip_mention("@claude — pourquoi ?", spellings) == "pourquoi ?"
    kept = "demande à claude ce qu'il en pense"
    assert conversation.strip_mention(kept, spellings) == kept


@case
def an_unblocking_needs_a_decision_and_a_reason():
    from ponos import unblocking

    said = "Le ticket B est en Done.\nDECISION: unblock\nREASON: B, dont il dépendait,\nest terminé."
    assert unblocking.decision(said) == ("unblock", "B, dont il dépendait, est terminé.")
    assert unblocking.decision("Réflexion.\nDECISION: unblock\nDECISION: keep\nREASON: toujours en attente")[0] == "keep", (
        "the last decision wins"
    )
    for unreadable in ("", "peut-être débloqué", "DECISION: unblock", "DECISION: maybe\nREASON: x"):
        assert unblocking.decision(unreadable) == ("", ""), unreadable


class _Unblocking(Runner):
    """A runner that only has what `_examine` asks of it, and says what it did."""

    moved: list
    comments_written: list

    def _project_of(self, ticket):
        return projects.Project(name="", path=None)

    def _body(self, ticket):
        return "Dépend du ticket B."

    def discussion(self, ticket):
        return []

    def _set(self, ticket, **values):
        self.moved.append(values)

    def _comment(self, ticket, text, discussion=""):
        self.comments_written.append(text)

    def comments(self, page_id):
        return [notion.Comment(text) for text in self.comments_written[-1:]]

    def _hold_credits(self, outcome):
        pass

    @property
    def workspace(self):
        return workspace.Workspace(tickets="db", projects="projects", agents="agents")


def _unblocking(answer: str, already: list[str] | None = None):
    runner = _bare_runner(None)
    runner.__class__ = _Unblocking
    runner.moved, runner.comments_written = [], list(already or [])
    page = notion.Page(id="p-ticket", url="", title="Ticket A")
    sessions: list[str] = []

    def fake_run(prompt_text, **kwargs):
        sessions.append(prompt_text)
        return session.Outcome(
            ok=True, blocked=False, session_id="s-1", summary="", log=Path("/tmp/none.jsonl"),
            answer=answer,
        )

    original, session.run = session.run, fake_run
    try:
        result = runner._examine(ticket_module.Ticket(page), "- [Done] Ticket B (b)")
    finally:
        session.run = original
    return runner, result, sessions


@case
def a_blocked_ticket_whose_cause_is_gone_goes_back_to_ready_with_the_reason():
    runner, result, sessions = _unblocking("DECISION: unblock\nREASON: Le ticket B est en Done.")
    assert runner.moved == [{"Status": runner.config.notion.state("ready")}], runner.moved
    assert len(runner.comments_written) == 1 and "Le ticket B est en Done." in runner.comments_written[0]
    assert (result["status"], result["reason"]) == ("unblocked", "Le ticket B est en Done.")
    assert "[Done] Ticket B" in sessions[0], "the session reads the whole board"


@case
def a_blocked_ticket_that_is_still_blocked_stays_and_says_why_once():
    runner, result, _ = _unblocking("DECISION: keep\nREASON: B n'est pas fini.")
    assert runner.moved == [], "nothing moves"
    assert "B n'est pas fini." in runner.comments_written[0]
    assert result["status"] == "kept-blocked"
    again, traced, _ = _unblocking("DECISION: keep\nREASON: B n'est pas fini.", runner.comments_written)
    assert len(again.comments_written) == 1, "the same reason is not written twice"
    assert traced["status"] == "kept-blocked", "but the decision is still traced"


@case
def a_session_that_does_not_conclude_never_unblocks_anything():
    runner, result, _ = _unblocking("Je ne sais pas trop.")
    assert runner.moved == [] and runner.comments_written == [] and result is None


# -- the « On » prompt -------------------------------------------------------


def _page(identifier: str, status: str, prompt: str = "", title: str = "") -> notion.Page:
    def text(kind: str, value: str) -> dict:
        return {"type": kind, kind: [{"plain_text": value}]}

    return notion.Page(
        id=identifier, url=f"https://notion.test/{identifier}", title=title or identifier,
        properties={
            "Status": {"type": "status", "status": {"name": status}},
            "On": text("rich_text", prompt),
        },
    )


class _OnBoard:
    """Pages by id, the way a board answers: the whole database, or one page."""

    def __init__(self, *pages: notion.Page) -> None:
        self.pages = {page.id: page for page in pages}

    def query(self, database, filter_=None):
        return list(self.pages.values())

    def page(self, page_id):
        return self.pages[page_id]

    def schema(self, database):
        return {"Status": "status", "On": "rich_text"}

    def set(self, identifier: str, status: str) -> None:
        self.pages[identifier] = _page(
            identifier, status, notion.read(self.pages[identifier], "On") if identifier in self.pages else ""
        )


class _OnRunner(_Unblocking):
    """A runner that has only what the « On » chapter asks of one."""

    def say(self, message):
        pass

    def under_reserve(self):
        return 0.0

    def _out_of_credit(self, outcome):
        return outcome.exhausted

    @property
    def voice(self):
        return voice.Voice("en")

    @property
    def environment(self):
        return {}


def _on_runner(board: _OnBoard, **runner_settings) -> _OnRunner:
    runner = _OnRunner.__new__(_OnRunner)
    runner.client = board
    runner.config = _config("")
    # Read at every call: the throttle has a test of its own.
    runner.config.runner.on_interval_seconds = 0
    for key, value in runner_settings.items():
        setattr(runner.config.runner, key, value)
    runner.dry_run, runner.moved, runner.comments_written = False, [], []
    runner._on_read = float("-inf")
    runner._comments = {}
    runner._claimed = set()
    return runner


def _a_session_that(effect=None, **outcome):
    """`session.run`, replaced by one that does `effect` while it runs."""
    seen: list[dict] = []

    def fake(prompt_text, **kwargs):
        seen.append({"prompt": prompt_text, **kwargs})
        if effect:
            effect()
        return session.Outcome(**{
            "ok": True, "blocked": False, "session_id": "s-on", "summary": "fait",
            "log": Path("/tmp/none.jsonl"), "answer": "RESULT: ok — fait", "cost_usd": 0.12,
            "seconds": 3.0, **outcome,
        })

    return seen, fake


@contextmanager
def _replacing(module, name: str, value):
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


@case
def a_status_is_a_change_only_from_the_second_time_it_is_seen_and_only_once():
    from ponos import transitions

    with _state_home():
        assert transitions.observe("t1", "Ready", title="A", depth_limit=3) == (0, ""), "a first sight"
        assert transitions.observe("t1", "Ready", title="A", depth_limit=3) == (0, ""), "nothing moved"
        found, old = transitions.observe("t1", "Done", title="A", depth_limit=3)
        assert found and old == "Ready"
        assert transitions.observe("t1", "Done", title="A", depth_limit=3) == (0, ""), (
            "the same change is not met twice: it is already the starting point"
        )
        assert [(row["old"], row["new"]) for row in transitions.pending(10)] == [("Ready", "Done")]
        # A ticket that loses its prompt is forgotten: the day it gets one again
        # is a first sight, not a change from a status it had months ago.
        transitions.forget(set())
        assert transitions.observe("t1", "Blocked", title="A", depth_limit=3) == (0, "")


@case
def the_on_prompt_of_a_ticket_runs_with_the_transition_and_is_closed_with_what_it_cost():
    from ponos import transitions

    with _state_home():
        board = _OnBoard(_page("t1", "Ready", "Si Done, crée le déploiement.", "Site"))
        runner = _on_runner(board)
        runner.transitions()  # the starting point
        board.set("t1", "Done")
        seen, fake = _a_session_that()
        with _replacing(session, "run", fake):
            results = runner.transitions()
        assert [entry["status"] for entry in results] == ["on-ok"], results
        prompt = seen[0]["prompt"]
        assert "Old status: Ready" in prompt and "New status: Done" in prompt, prompt
        assert "Si Done, crée le déploiement." in prompt
        assert seen[0]["max_budget_usd"] == 1.0, "a ceiling by default"
        assert seen[0]["timeout_minutes"] == 10
        (row,) = transitions.history("t1")
        assert (row["state"], row["cost_usd"], row["result"]) == ("ok", 0.12, "fait"), row


@case
def what_an_execution_moves_or_creates_never_wakes_a_prompt_and_its_children_are_one_generation_down():
    from ponos import transitions

    with _state_home():
        board = _OnBoard(_page("t1", "Ready", "Crée un ticket de suivi puis passe-moi en Done."))
        runner = _on_runner(board)
        runner.transitions()
        board.set("t1", "In progress")

        def effect():
            # What the prompt does: moves its own ticket, makes another, with a prompt too.
            board.set("t1", "Done")
            board.pages["t2"] = _page("t2", "Ready", "Moi aussi.")

        seen, fake = _a_session_that(effect)
        with _replacing(session, "run", fake):
            runner._on_read = float("-inf")
            runner.transitions()
            assert len(seen) == 1
            # The next reading: neither the move of t1 nor the birth of t2 is a change.
            runner._on_read = float("-inf")
            assert runner.transitions() == [] and len(seen) == 1, "no loop"
            # But t2 is a ticket like another from now on, one generation down.
            board.set("t2", "Done")
            runner._on_read = float("-inf")
            assert [e["status"] for e in runner.transitions()] == ["on-ok"]
            (row,) = transitions.history("t2")
            assert row["depth"] == 1, row


@case
def a_chain_of_tickets_made_by_prompts_stops_at_the_depth_the_file_allows():
    from ponos import transitions

    with _state_home():
        board = _OnBoard(_page("t1", "Ready", "Fais un ticket."))
        runner = _on_runner(board, on_max_depth=1)
        runner.transitions()
        generation = {"n": 0}

        def effect():
            # Every execution makes the next ticket of the chain, with the same prompt.
            generation["n"] += 1
            name = f"c{generation['n']}"
            board.pages[name] = _page(name, "Ready", "Fais un ticket.")

        seen, fake = _a_session_that(effect)
        with _replacing(session, "run", fake):
            board.set("t1", "Done")
            for _ in range(4):
                runner._on_read = float("-inf")
                runner.transitions()
                # What the chain does by itself: each new ticket is done by somebody.
                for name in [n for n in board.pages if n.startswith("c")]:
                    if notion.read(board.pages[name], "Status") != "Done":
                        board.set(name, "Done")
        # t1 (depth 0) and c1 (depth 1) ran; c2 would be depth 2 > the limit of 1.
        assert generation["n"] == 2, generation
        skipped = [row for row in transitions.history("c2") if row["state"] == "skipped"]
        assert skipped and "deeper" in skipped[0]["result"], transitions.history("c2")


@case
def an_execution_that_fails_or_overspends_is_commented_and_never_touches_a_status():
    from ponos import transitions

    with _state_home():
        board = _OnBoard(_page("t1", "Ready", "Fais-le."))
        runner = _on_runner(board)
        runner.transitions()
        board.set("t1", "Blocked")
        _, fake = _a_session_that(ok=False, blocked=True, over_budget=True, answer="", summary="")
        with _replacing(session, "run", fake):
            results = runner.transitions()
        assert [entry["status"] for entry in results] == ["on-failed"], results
        assert runner.moved == [], "the status is the board's"
        assert len(runner.comments_written) == 1
        assert "Ready → Blocked" in runner.comments_written[0] and "1.00" in runner.comments_written[0]
        assert transitions.history("t1")[0]["state"] == "failed"
        runner._on_read = float("-inf")
        assert runner.transitions() == [], "a failure is not tried again by itself"


@case
def an_execution_that_never_started_for_want_of_credit_is_still_to_run():
    from ponos import transitions

    with _state_home():
        board = _OnBoard(_page("t1", "Ready", "Fais-le."))
        runner = _on_runner(board)
        runner.transitions()
        board.set("t1", "Done")
        _, broke = _a_session_that(ok=False, exhausted=True, answer="")
        with _replacing(session, "run", broke):
            assert runner.transitions() == []
        assert [row["state"] for row in transitions.history("t1")] == ["pending"]
        seen, fake = _a_session_that()
        with _replacing(session, "run", fake):
            runner._on_read = float("-inf")
            assert len(runner.transitions()) == 1 and len(seen) == 1


@case
def the_board_is_read_for_moved_statuses_no_more_often_than_the_file_says():
    with _state_home():
        board = _OnBoard(_page("t1", "Ready", "Fais-le."))
        runner = _on_runner(board, on_interval_seconds=30)
        reads = []
        original = board.query
        board.query = lambda *a, **k: (reads.append(1), original(*a, **k))[1]
        runner.transitions()
        runner.transitions()
        runner.transitions()
        assert len(reads) == 1, "three passes within the interval, one reading"
        runner.config.runner.on = False
        runner._on_read = float("-inf")
        runner.transitions()
        assert len(reads) == 1, "runner.on = false reads nothing"


@case
def an_execution_a_dead_run_left_open_is_closed_and_never_run_again():
    from ponos import transitions

    with _state_home():
        transitions.observe("t1", "Ready", title="A", depth_limit=3)
        found, _ = transitions.observe("t1", "Done", title="A", depth_limit=3)
        assert transitions.start(found) and not transitions.start(found), "taken once"
        assert transitions.abandon(-5) == 1, "older than the future: any execution left open"
        (row,) = transitions.history("t1")
        assert row["state"] == "failed" and "interrupted" in row["result"], row
        assert transitions.pending(10) == []


class _KnownCommentClient:
    """Comments that say who wrote them, as Notion's do."""

    def __init__(self, comments: list[notion.Comment]):
        self._comments = comments

    def comments(self, page_id: str) -> list[notion.Comment]:
        return self._comments

    def me(self) -> str:
        return ME

    def my_name(self) -> str:
        return "Ponos"


def _knowing(comments: list[notion.Comment]) -> Runner:
    runner = _bare_runner(_KnownCommentClient(comments))
    runner.config = _config("")
    runner._me = None  # asked of Notion, as in a real run
    runner._spellings = None
    return runner


def _ticket():
    return type("T", (), {"page": notion.Page(id="p", url="", title="t")})()


REPORT_BY_US = _said(f"{legacy.OLD}@laptop — blocked.\nQuel en-tête ?", by=ME)


@case
def talking_on_a_ticket_does_not_put_it_back_in_the_queue():
    """Its own answer is not an instruction it was given — or every conversation
    would end in a run nobody asked for."""
    talked = [
        REPORT_BY_US,
        _said("@claude pourquoi tu demandes ?"),
        _said("parce que la page en a deux.", by=ME),
    ]
    assert not _knowing(talked)._answered(_ticket())
    # And the moment you actually answer the question, it runs again.
    assert _knowing([*talked, _said("celui du dashboard.")])._answered(_ticket())


@case
def an_answer_given_on_your_phone_is_still_your_answer():
    """It carries the runner's token — the runner is what posts it — and it is
    the ticket's author speaking. So it wakes the ticket exactly as the same
    word typed into Notion would, rather than reading as the runner's own last
    word and closing the very question it answers."""
    relayed = channels.answer(
        channels.Reply(channel="telegram", text="oui", ticket="p", title="t", who="Salvador")
    )
    assert conversation.is_relayed(relayed), "channels and conversation share one sentence"
    assert not conversation.ours(_said(relayed, by=ME), ME)
    assert _knowing([REPORT_BY_US, _said(relayed, by=ME)])._answered(_ticket())
    # And what the runner says in its own voice still is not an answer to itself.
    assert not _knowing([REPORT_BY_US, _said("parce que la page en a deux.", by=ME)])._answered(
        _ticket()
    )


@case
def its_own_answers_are_not_read_back_as_yours():
    runner = _knowing([
        REPORT_BY_US,
        _said("pourquoi ?"),
        _said("parce que la page en a deux.", by=ME),
        _said("celui du dashboard."),
    ])
    lines = runner.discussion(_ticket())
    assert lines == [
        "a previous run: blocked. Quel en-tête ?",
        "the ticket's author: pourquoi ?",
        "answered in the comments, by us: parce que la page en a deux.",
        "the ticket's author: celui du dashboard.",
    ], lines


@case
def a_thread_transcript_tells_its_two_voices_apart():
    thread = conversation.threads([
        _said(f"{legacy.OLD}@laptop — done.", by=ME),
        _said("pourquoi ?"),
        _said("parce que.", by=ME),
        _said("et sinon ?"),
    ])[0]
    lines = conversation.transcript(thread, ME)
    assert lines == [
        f"you: {legacy.OLD}@laptop — done.",
        "them: pourquoi ?",
        "you: parce que.",
    ], lines
    assert all("et sinon" not in line for line in lines), "the message being answered is not history"


@case
def the_scan_moves_across_the_board_a_window_at_a_time():
    """One request per page, and a run that can come round every ten seconds."""
    ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    pages = [f"p{index}" for index in range(5)]
    assert ledger.rotate(pages, 2) == ["p0", "p1"]
    assert ledger.rotate(pages, 2) == ["p2", "p3"]
    assert ledger.rotate(pages, 2) == ["p4", "p0"], "it wraps rather than starting over"
    assert ledger.rotate(pages, 10) == pages, "a window wider than the board is the board"
    assert ledger.rotate([], 2) == []


@case
def the_pass_holds_off_until_its_own_interval_has_passed():
    ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    assert ledger.due(60), "a runner that has never looked is due at once"
    ledger.stamp()
    assert not ledger.due(60)
    assert ledger.due(0)


@case
def what_the_runner_remembers_survives_a_restart():
    path = Path(tempfile.mkdtemp()) / "ponos.db"
    ledger = conversation.Ledger(database=path)
    ledger.remember_page("3ca45168-0af4-80ae-9443-de0b65d9abf8")
    ledger.remember_thread("d1", session="s-1", comment="c-1")
    ledger.cursor = 3
    ledger.save()

    again = conversation.Ledger.load(path)
    assert again.known_pages() == ["3ca451680af480ae9443de0b65d9abf8"], "dashes and all"
    assert again.session_of("d1") == "s-1"
    assert again.cursor == 3
    assert conversation.Ledger.load(Path(tempfile.mkdtemp()) / "ponos.db").known_pages() == []


class _ThreadClient:
    """Pages with comments on them, and nothing else."""

    def __init__(self, pages: dict[str, list[notion.Comment]]):
        self.pages = pages
        self.asked: list[str] = []

    def comments(self, page_id: str) -> list[notion.Comment]:
        self.asked.append(page_id)
        if page_id not in self.pages:
            raise notion.NotionError("404 could not find block")
        return self.pages[page_id]

    def my_name(self) -> str:
        return "Ponos"


def _talking(pages: dict[str, list[notion.Comment]], *, claimed: set[str] = frozenset(), scan=20):
    runner = _bare_runner(_ThreadClient(pages))
    runner.config = _config("")
    runner.config.runner.reply_scan = scan
    runner._spellings = None  # resolved from the client, as in a real run
    runner._me = ME
    runner._claimed = set(claimed)
    runner._ledger_lock = threading.Lock()
    runner._ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    for page in pages:
        runner._ledger.remember_page(page)
    return runner


REPLIED_TO = [
    _said(f"{legacy.OLD}@laptop — done.\nFait.", by=ME),
    _said("pourquoi ce nom de branche ?"),
]


@case
def a_ticket_about_to_run_is_left_to_the_run_that_will_read_it():
    """The comment is already going into its prompt; two answers would be one
    too many, and one of them would be the runner talking over itself."""
    runner = _talking({"pone": REPLIED_TO, "ptwo": REPLIED_TO}, claimed={"ptwo"})
    assert [page for page, _ in runner._pending(ME)] == ["pone"]


@case
def a_pass_answers_one_thread_per_page_and_stops_at_five():
    two = [
        _said(f"{legacy.OLD}@laptop — done.", by=ME, thread="d1"),
        _said("pourquoi ?", thread="d1"),
        _said("@claude et ici ?", thread="d2"),
    ]
    runner = _talking({"pone": two})
    pending = runner._pending(ME)
    assert len(pending) == 1 and pending[0][1].discussion == "d1", "the next pass takes the other"

    crowd = {f"page{index}": REPLIED_TO for index in range(9)}
    assert len(_talking(crowd)._pending(ME)) == conversation.ANSWERS


@case
def a_page_that_cannot_be_read_costs_that_page_and_nothing_else():
    runner = _talking({"ptwo": REPLIED_TO})
    runner._ledger.remember_page("pgone")
    assert [page for page, _ in runner._pending(ME)] == ["ptwo"]


@case
def the_pages_this_run_has_already_read_cost_no_second_request():
    runner = _talking({"pone": REPLIED_TO})
    runner._comments["pone"] = REPLIED_TO  # as `woken` leaves it
    assert len(runner._pending(ME)) == 1
    assert runner.client.asked == [], "nothing was asked of Notion twice"


class _TalkingClient(_ThreadClient):
    """A page, its discussion, and what got written back into it."""

    def __init__(self, pages, body: str = "Supprimer l'entête."):
        super().__init__(pages)
        self._body = body
        self.posted: list[tuple[str, str, str]] = []

    def me(self) -> str:
        return ME

    def page(self, page_id: str) -> notion.Page:
        return notion.Page(id=page_id, url=f"https://notion.so/{page_id}", title="Un ticket")

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._body

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.posted.append((page_id, text, discussion_id))

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        raise AssertionError("a conversation moves nothing on the board")


@contextmanager
def _no_session(
    answer: str = "Parce que la branche d'hier était déjà en revue.", ok=True, writes=None
):
    """Claude, replaced by its answer. Records how it was asked.

    `ok` may be a list, read one entry per call: that is how a session that
    cannot be resumed is told from one that has nothing to say. `writes` is
    `{name: text}` left in the working directory — which is how a document
    ticket answers, the session writing ANSWER.md rather than saying anything.
    """
    calls: list[dict] = []
    verdicts = list(ok) if isinstance(ok, (list, tuple)) else None

    def fake_run(prompt_text, **kwargs):
        calls.append({"prompt": prompt_text, **kwargs})
        good = verdicts.pop(0) if verdicts else (ok if verdicts is None else True)
        for name, text in (writes or {}).items():
            (Path(kwargs["cwd"]) / name).write_text(text, encoding="utf-8")
        return session.Outcome(
            ok=good, blocked=False, session_id=kwargs.get("session_id", "s-1"),
            summary="", log=Path("/tmp/none.jsonl"), answer=answer if good else "",
            error="" if good else "claude exited with code 1", seconds=12.0, cost_usd=0.01,
        )

    original = session.run
    session.run = fake_run
    try:
        yield calls
    finally:
        session.run = original


@case
def answering_a_comment_writes_in_its_thread_and_nowhere_else():
    with _state_home(), _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", context="Je suis Salvador.")
        answered = runner.converse()

    assert len(answered) == 1 and answered[0]["status"] == "answered"
    page, text, discussion = runner.client.posted[0]
    assert (page, discussion) == ("pone", "d1"), "under the question, not at the bottom"
    assert text == "Parce que la branche d'hier était déjà en revue."

    asked = calls[0]
    assert asked["permission_mode"] == "plan", "it talks; it does not work"
    assert asked["resume"] is False and asked["timeout_minutes"] == 10
    assert "pourquoi ce nom de branche ?" in asked["prompt"]
    assert "Supprimer l'entête." in asked["prompt"], "it knows the ticket it is under"
    assert "Je suis Salvador." in asked["prompt"], "and who it is answering"


@case
def a_second_question_lands_in_the_same_conversation():
    with _state_home(), _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
        runner.converse()

        again = [*REPLIED_TO, _said("et le footer ?", ident="c-later")]
        runner.client.pages["pone"] = again
        runner._comments.clear()
        runner._ledger.at = 0.0  # the interval, not the point of this test
        runner.converse()

    assert len(calls) == 2
    assert calls[1]["resume"] is True and calls[1]["session_id"] == calls[0]["session_id"]
    assert calls[1]["prompt"].strip().endswith("et le footer ?")
    assert "Supprimer l" not in calls[1]["prompt"], "a resumed session has the frame already"


@case
def a_session_that_says_nothing_is_still_answered_for():
    """Silence in a thread reads as being ignored, which is worse than a failure."""
    with _state_home(), _no_session(ok=False) as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
        runner.converse()

    assert len(calls) == 1, "nothing to resume, so nothing to retry"
    assert "could not answer" in runner.client.posted[0][1]
    assert "log is" in runner.client.posted[0][1], "and where to go and look"


@case
def a_conversation_whose_session_is_gone_starts_a_new_one():
    """The transcript was pruned, or the machine changed. Notion still has the
    thread, which is enough to carry on from."""
    with _state_home(), _no_session(ok=[True, False, True]) as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
        runner.converse()

        runner.client.pages["pone"] = [*REPLIED_TO, _said("et le footer ?", ident="c-later")]
        runner._comments.clear()
        runner._ledger.at = 0.0
        runner.converse()

    assert [call["resume"] for call in calls] == [False, True, False]
    assert calls[2]["session_id"] != calls[1]["session_id"]
    assert "Supprimer l" in calls[2]["prompt"], "a fresh session is told everything again"
    assert len(runner.client.posted) == 2 and "could not answer" not in runner.client.posted[1][1]


@case
def a_pass_that_is_turned_off_or_too_soon_asks_notion_nothing():
    with _state_home(), _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner.config.runner.reply = False
        assert runner.converse() == []

        runner.config.runner.reply = True
        runner._ledger.stamp()
        assert runner.converse() == [], "the interval has not passed"
        assert runner.client.asked == [] and calls == []


@case
def a_conversation_prompt_says_what_it_is_not_allowed_to_do():
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="Animalink", title="t", body="b", where="Repository: /r", url="u",
        message="pourquoi ce nom ?",
        thread=["them: pourquoi ?"],
        context="Je suis Salvador.",
        brief="Ton: direct.",
        agent_name="Rédacteur",
        agent_brief="Deux angles.",
        comments=["a previous run: done. fait"],
    )
    assert "talking, not working" in text
    order = [text.index(mark) for mark in (
        "b",                        # the ticket itself
        "already been said",        # then what was said about it
        "Je suis Salvador.",        # then the widest frame
        "Ton: direct.",             # then the project
        "Deux angles.",             # then the role
        "# Context",                # then the mechanics
        "This thread so far",       # then the conversation being had
        "pourquoi ce nom ?",        # and last, the message to answer
    )]
    assert order == sorted(order), order
    # A resumed session is sent the message and not the whole frame again.
    assert prompt.message_of(text) == "pourquoi ce nom ?"


@case
def a_ticket_without_a_project_still_reads_as_a_sentence():
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="", title="t", body="", where="Working directory: /tmp/x", url="u",
        message="et alors ?",
    )
    assert "that belongs to no project" in text
    assert "This thread so far" not in text and "# Your role" not in text
    assert "everything is in the title" in text


@case
def an_answer_too_long_for_a_comment_is_cut_where_it_breathes():
    assert conversation.trim("court") == "court"
    long = ("Une phrase. " * 200).strip()
    cut = conversation.trim(long, limit=200)
    assert len(cut) < 400 and cut.endswith("ask for it in pieces.")
    assert cut.split("[…]")[0].rstrip().endswith("."), "cut on a sentence, not mid-word"


@case
def the_role_sits_between_the_project_and_the_mechanics():
    text = prompt.build(
        prompt.DEFAULT,
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u",
        context="Je suis Salvador.",
        brief="Ton: direct.",
        agent_name="Rédacteur",
        agent_brief="Deux ou trois angles, toujours.",
        comments=["the ticket's author: plutôt court."],
    )
    order = [text.index(mark) for mark in (
        "b",                        # the ticket itself
        "already been said",        # then what was said about it
        "Je suis Salvador.",        # then the widest frame
        "Ton: direct.",             # then the project
        "Deux ou trois angles",     # then the role
        "# Context",                # then the mechanics
    )]
    assert order == sorted(order), order
    assert "# Your role — Rédacteur" in text


@case
def a_ticket_with_no_agent_and_no_comments_reads_as_before():
    common = dict(
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    bare = prompt.build(prompt.DEFAULT, **common)
    assert "# Your role" not in bare and "already been said" not in bare
    assert prompt.build(prompt.DEFAULT, **common, comments=[], agent_brief="  ") == bare


# -- session outcome ---------------------------------------------------------


@case
def a_verdict_is_read_from_the_last_result_line():
    assert session._verdict("blah\nRESULT: ok — removed the header") == "ok"
    assert session._verdict("**RESULT: blocked — which page?**") == "blocked"
    assert session._verdict("nothing of the sort") == ""
    # The last one wins: an agent may quote the format before using it.
    assert session._verdict("RESULT: blocked — x\nRESULT: ok — y") == "ok"


@case
def a_summary_drops_the_verdict_it_repeats():
    assert session._summary("x\nRESULT: ok — removed the header") == "removed the header"
    assert session._summary("**RESULT: blocked — which page?**") == "which page?"
    assert session._summary("no verdict here") == "no verdict here"


@case
def project_keys_match_what_claude_code_writes_on_disk():
    """Observed against real ~/.claude/projects folders."""
    assert session.project_key(Path("/home/salva/workspace/labo/trader-ia")) == (
        "-home-salva-workspace-labo-trader-ia"
    )
    assert session.project_key(
        Path("/home/salva/.local/state/ponos/worktrees/trader-ia-3ca45168")
    ) == "-home-salva--local-state-ponos-worktrees-trader-ia-3ca45168"


@case
def a_remote_link_carries_its_host():
    """Once the runner is on a server, the session is there too.

    A link with a host resolves to an ssh command instead of a local claude,
    which is what keeps the Session column clickable from a laptop.
    """
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("abc-123", "/srv/work/app", "salva@vps")
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    assert query["host"] == ["salva@vps"]
    assert query["cwd"] == ["/srv/work/app"]
    # Without a host the link stays purely local.
    assert "host=" not in session.deep_link("abc-123", "/srv/work/app")


@case
def a_deep_link_survives_a_round_trip():
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("0486a9fd-44f6-4fff-9dee-9e58bc4062ba", "/home/me/my work")
    parsed = urlparse(link)
    assert parsed.scheme == session.SCHEME
    assert parsed.netloc == "session"
    assert parsed.path.strip("/") == "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"
    assert parse_qs(parsed.query)["cwd"][0] == "/home/me/my work"
    assert session.deep_link("abc") == "ponos://session/abc"


@case
def a_prompt_never_reaches_the_command_line():
    """The prompt goes on stdin, whatever its size, and argv keeps only options.

    Too long, an argument is refused by Linux before the session exists (E2BIG
    past 128 KiB). Short, it is worse: `ps` shows it to every user, and
    `pkill -f` matches it — a ticket quoting the last run's `vite --port 5199`
    had its session kill itself with `pkill -f "vite --port 5199"`. The marker
    here is drawn fresh, so this test cannot kill anything but its own fake.
    """
    marker = f"vite --port {uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        seen = home / "seen.json"
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, shutil, subprocess, sys\n"
            "prompt = sys.stdin.read()\n"
            # What the session that died did: kill a server by its command line.
            f"if shutil.which('pkill'): subprocess.run(['pkill', '-f', {marker!r}])\n"
            f"open({str(seen)!r}, 'w').write(json.dumps({{'args': sys.argv[1:], 'prompt': prompt}}))\n"
            "print(json.dumps({'type': 'result', 'result': 'RESULT: ok', 'session_id': 's'}))\n"
        )
        (home / "claude").chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        prompts = {
            "short": f"Restart the server: {marker}.",
            "long": f"{marker} " + "x" * 300_000,  # past the 128 KiB Linux takes
        }
        try:
            for name, text in prompts.items():
                for resume in (False, True):
                    outcome = session.run(
                        text, cwd=home, log=home / f"{name}.jsonl", timeout_minutes=1,
                        session_id="0486a9fd-44f6-4fff-9dee-9e58bc4062ba", resume=resume,
                    )
                    assert outcome.ok, (name, resume, outcome.error)
                    got = json.loads(seen.read_text())
                    assert got["prompt"] == text, (name, resume)
                    assert not any(marker in word for word in got["args"]), got["args"]
                    assert all(len(word) < 100 for word in got["args"]), got["args"]
        finally:
            os.environ["PATH"] = previous


@case
def a_link_cannot_slip_an_option_into_ssh_or_claude():
    """A link is something anybody can paste into a cell, and a click runs it.

    `host=-oProxyCommand=…` is not a machine, it is an ssh option that runs a
    command before any connection is tried — and an identifier starting with a
    dash would be an option to `claude` just the same. Both are refused before
    anything is looked up, and the destination ssh is given comes after `--`.
    """
    identifier = "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"
    for uri in (
        f"ponos://session/{identifier}?host=-oProxyCommand=touch%20/tmp/owned",
        f"ponos://session/{identifier}?host=me%40box%20-oProxyCommand=x",
        f"ponos://session/{identifier}?host=me;id",
        "ponos://session/--dangerously-skip-permissions",
        "ponos://session/abc$(id)",
    ):
        try:
            session.resume_command(uri)
        except ValueError as error:
            assert str(error), uri
        else:
            raise AssertionError(f"accepted: {uri}")

    original = shutil.which
    session.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        cwd, command = session.resume_command(
            session.deep_link(identifier, "/srv/work/app", "salva@vps.example.org")
        )
        _, bracketed = session.resume_command(
            f"ponos://session/{identifier}?host=me%40%5B::1%5D"
        )
    finally:
        session.shutil.which = original
    assert command[:4] == ["ssh", "-t", "--", "salva@vps.example.org"], command
    assert command[4].endswith(f"claude --resume {identifier}"), command
    assert bracketed[3] == "me@[::1]", bracketed


# -- Notion encoding ---------------------------------------------------------


@contextmanager
def _notion_answering(*answers):
    """Notion's transport replaced by a script: each call takes the next answer.

    An answer is a dict (the JSON Notion returns) or an exception to raise, the
    way `urlopen` raises it. Yields the calls made, as (method, path), and the
    pauses taken between them — none of which are slept for real.
    """
    import urllib.error
    import urllib.request

    calls: list[tuple[str, str]] = []
    pauses: list[float] = []
    queue = list(answers)

    class _Response:
        def __init__(self, body: dict) -> None:
            self._body = json.dumps(body).encode()

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    def urlopen(request, timeout=None):
        calls.append((request.get_method(), request.full_url.split("/v1", 1)[-1]))
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return _Response(answer)

    original_open, original_sleep = urllib.request.urlopen, notion.time.sleep
    notion.urllib.request.urlopen = urlopen
    notion.time.sleep = pauses.append
    try:
        yield calls, pauses
    finally:
        notion.urllib.request.urlopen = original_open
        notion.time.sleep = original_sleep


def _http_error(code: int, retry_after: str = ""):
    import email.message
    import urllib.error

    headers = email.message.Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    body = io.BytesIO(json.dumps({"message": f"status {code}"}).encode())
    return urllib.error.HTTPError("https://api.notion.com/v1/x", code, "no", headers, body)


@case
def the_console_starts_on_the_file_install_sh_leaves():
    """`serve` used to require a usable configuration, and exit 2 without a
    Notion token — so the console whose first connection *asks* for that token
    could not be reached, and its unit restarted in a loop on a fresh install.

    It starts now; the board it cannot read yet says why without asking Notion,
    and `run` — the timer's command — still refuses, out loud.
    """
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    with _state_home(), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.toml"
        shutil.copy(example, path)
        previous = os.environ.get("PONOS_CONFIG")
        os.environ["PONOS_CONFIG"] = str(path)
        printed, errors = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(errors):
                assert cli_main(["serve", "--print-token"]) == 0, errors.getvalue()
                try:
                    cli_main(["run"])
                except SystemExit as stopped:
                    assert stopped.code == 2
                else:
                    raise AssertionError("run went ahead with no Notion token")
        finally:
            if previous is None:
                os.environ.pop("PONOS_CONFIG", None)
            else:
                os.environ["PONOS_CONFIG"] = previous
        assert printed.getvalue().strip(), "a token to open the console with"
        assert "notion.token" in errors.getvalue()

    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("the placeholder token was sent to Notion")

    original = urllib.request.urlopen
    notion.urllib.request.urlopen = refuse
    try:
        for token in ("", C.PLACEHOLDER):
            try:
                notion.Client(token)._request("POST", "/databases/d/query", {})
            except notion.NotionError as error:
                assert "no Notion token yet" in str(error)
            else:
                raise AssertionError("a board with no token was read")
    finally:
        notion.urllib.request.urlopen = original


@case
def a_read_that_times_out_is_asked_again_and_says_notion_when_it_gives_up():
    """A timeout or a reset while reading used to escape as a bare OSError.

    Nothing catches an OSError around a Notion call — `StoreError` is what the
    runner is written to survive — so one slow answer took the whole pass down.
    """
    import urllib.error

    client = notion.Client("ntn_x")
    with _notion_answering(TimeoutError("timed out"), ConnectionResetError(104, "reset"),
                           {"object": "page", "id": "p"}) as (calls, pauses):
        assert client._request("GET", "/pages/p") == {"object": "page", "id": "p"}
    assert len(calls) == 3 and len(pauses) == 2, (calls, pauses)

    with _notion_answering(*[TimeoutError("timed out")] * notion.MAX_ATTEMPTS) as (calls, _):
        try:
            client._request("POST", "/databases/d/query", {})
        except notion.NotionError as error:
            assert "gave up" in str(error), error
        else:
            raise AssertionError("a Notion that never answers was taken for an answer")
    assert len(calls) == notion.MAX_ATTEMPTS, "a query is a read, and is retried"

    refused = urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    with _notion_answering(refused, {"results": []}) as (calls, _):
        assert client._request("GET", "/users/me") == {"results": []}


@case
def a_comment_is_never_posted_twice_on_the_strength_of_a_silence():
    """A write that may have landed is not sent again: a duplicate comment is
    worse than an error. Only what Notion refused outright — a 429, or a
    connection that never carried the request — is safe to send twice."""
    import urllib.error

    client = notion.Client("ntn_x")
    for silence in (TimeoutError("timed out"), ConnectionResetError(104, "reset"), _http_error(502)):
        with _notion_answering(silence, {"object": "comment"}) as (calls, _):
            try:
                client._request("POST", "/comments", {"rich_text": []})
            except notion.NotionError:
                pass
            else:
                raise AssertionError(f"{silence!r} was retried on a write")
        assert calls == [("POST", "/comments")], (silence, calls)

    refused = urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    with _notion_answering(refused, {"object": "comment"}) as (calls, _):
        assert client._request("POST", "/comments", {}) == {"object": "comment"}
    assert len(calls) == 2, "never sent is safe to send"

    with _notion_answering(_http_error(429, retry_after="7"), {"object": "comment"}) as (calls, pauses):
        assert client._request("POST", "/comments", {}) == {"object": "comment"}
    assert len(calls) == 2 and pauses == [7.0], (calls, pauses)

    with _notion_answering(_http_error(429, retry_after="86400"), {}) as (_, pauses):
        client._request("GET", "/users/me")
    assert pauses == [notion.LONGEST_WAIT], "a day is not a pause, it is a refusal"

    with _notion_answering(TimeoutError("timed out"), {}) as (calls, _):
        try:
            client._request("PATCH", "/blocks/b/children", {"children": []})
        except notion.NotionError:
            pass
    assert len(calls) == 1, "appending blocks twice is two copies of them"

    with _notion_answering(_http_error(503), {"id": "p"}) as (calls, _):
        client._request("PATCH", "/pages/p", {"properties": {}})
    assert len(calls) == 2, "setting a value twice is setting it once"


@case
def the_api_is_notions_unless_a_test_says_otherwise():
    """The one seam `tests/functional.py` needs, and what it must not become.

    An installation talks to Notion and to nowhere else: the variable is unset,
    and an empty one is as good as unset — otherwise a `PONOS_NOTION_API=`
    left in a unit file would point a real runner at nothing at all.
    """
    previous = os.environ.get(notion.API_ENV)
    try:
        os.environ.pop(notion.API_ENV, None)
        assert notion.endpoint() == notion.API
        for blank in ("", "   "):
            os.environ[notion.API_ENV] = blank
            assert notion.endpoint() == notion.API, f"“{blank}” is not an endpoint"
        os.environ[notion.API_ENV] = "http://127.0.0.1:8123/v1/"
        assert notion.endpoint() == "http://127.0.0.1:8123/v1", "a trailing slash doubles one"
    finally:
        if previous is None:
            os.environ.pop(notion.API_ENV, None)
        else:
            os.environ[notion.API_ENV] = previous


@case
def values_are_encoded_for_the_type_the_database_declares():
    assert notion._encode("status", "Done") == {"status": {"name": "Done"}}
    assert notion._encode("select", "Done") == {"select": {"name": "Done"}}
    assert notion._encode("url", "https://x") == {"url": "https://x"}
    assert notion._encode("number", 1.5) == {"number": 1.5}
    # A property the database does not have is skipped, not guessed at.
    assert notion._encode(None, "Done") is None
    assert notion._encode("status", None) is None


@case
def long_text_is_split_below_notions_limit():
    chunks = notion._rich_text("a" * 5000)
    assert len(chunks) == 3
    assert all(len(chunk["text"]["content"]) <= 1900 for chunk in chunks)
    assert notion._rich_text("") == [{"type": "text", "text": {"content": ""}}]


@case
def blocks_become_readable_text_for_the_prompt():
    todo = {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "fait"}]}}
    assert notion._block_text(todo, 0) == "- [x] fait"
    heading = {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Titre"}]}}
    assert notion._block_text(heading, 0) == "## Titre"
    divider = {"type": "divider", "divider": {}}
    assert notion._block_text(divider, 0) == "---"


@case
def properties_are_read_back_as_plain_python():
    page = notion.Page(
        id="x", url="u", title="t",
        properties={
            "Status": {"type": "status", "status": {"name": "Done"}},
            "Empty": {"type": "status", "status": None},
            "Cost": {"type": "number", "number": 0.42},
            "Project": {"type": "relation", "relation": [{"id": "abc"}]},
            "Session": {"type": "url", "url": "ponos://session/x"},
        },
    )
    assert notion.read(page, "Status") == "Done"
    assert notion.read(page, "Empty") is None
    assert notion.read(page, "Cost") == 0.42
    assert notion.read(page, "Project") == ["abc"]
    assert notion.read(page, "Session") == "ponos://session/x"
    assert notion.read(page, "Absent") is None


# -- markdown to Notion blocks -----------------------------------------------


@case
def markdown_keeps_its_shape_as_notion_blocks():
    blocks = markdown.to_blocks(
        "# Plan\n\nUn **paragraphe**.\n\n## Étapes\n- point\n- [x] fait\n1. numéroté\n\n"
        "> citation\n\n---\n\n```python\nprint(1)\n```\n"
    )
    assert [block["type"] for block in blocks] == [
        "heading_1", "paragraph", "heading_2", "bulleted_list_item",
        "to_do", "numbered_list_item", "quote", "divider", "code",
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


# -- scheduling --------------------------------------------------------------


@case
def a_bare_date_means_the_start_of_that_day_here():
    """Not midnight UTC: a ticket dated "30 August" starts on the 30th, locally."""
    from datetime import datetime

    from ponos.schedules import scheduled_for

    moment = scheduled_for("2026-08-30")
    assert moment is not None and moment.tzinfo is not None
    assert (moment.year, moment.month, moment.day, moment.hour) == (2026, 8, 30, 0)
    assert moment.utcoffset() == datetime.now().astimezone().utcoffset()


@case
def a_date_with_a_time_keeps_its_offset():
    from ponos.schedules import scheduled_for

    moment = scheduled_for("2026-08-30T14:30:00.000+02:00")
    assert moment is not None
    assert (moment.hour, moment.minute) == (14, 30)
    assert moment.utcoffset().total_seconds() == 7200


@case
def an_unreadable_date_never_holds_a_ticket_back():
    """A value the runner cannot parse must not silently freeze a ticket."""
    from ponos.schedules import scheduled_for

    assert scheduled_for(None) is None
    assert scheduled_for("") is None
    assert scheduled_for("bientôt") is None


@case
def notion_truncates_a_datetime_to_the_minute():
    """Not our doing, but it decides how precise scheduling can be.

    Sending 14:48:27 stores 14:48:00, so a ticket fires at the top of the minute
    it names. Worth pinning: a future change here would look like the runner
    firing early.
    """
    from ponos.schedules import scheduled_for

    stored = scheduled_for("2026-08-28T14:48:00.000+02:00")
    assert stored is not None and (stored.hour, stored.minute, stored.second) == (14, 48, 0)


@contextmanager
def _paris():
    """The machine in Paris for a moment: what a schedule's hours are said in."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Paris"
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()


def _walk(cadence: str, at: str, day: str, start: str, count: int) -> list[str]:
    """`count` occurrences in a row, each computed from the one before — the calendar's walk."""
    found: list[str] = []
    after = datetime.fromisoformat(start).astimezone()
    for _ in range(count):
        after = schedules.next_occurrence(cadence, at, day, after=after)
        found.append(after.strftime("%Y-%m-%d %H:%M %Z"))
    return found


@case
def a_schedule_keeps_its_wall_clock_hour_across_the_change_to_winter_time():
    """The clocks go back on 25 October 2026: nine in the morning stays nine."""
    with _paris():
        assert schedules.timezone_name() == "Europe/Paris"
        assert _walk("Daily", "09:00", "", "2026-10-23T12:00:00+02:00", 4) == [
            "2026-10-24 09:00 CEST",
            "2026-10-25 09:00 CET",
            "2026-10-26 09:00 CET",
            "2026-10-27 09:00 CET",
        ]
        # An hour that does not exist (02:30 on 29 March) lands after the jump.
        assert _walk("Daily", "02:30", "", "2026-03-28T12:00:00+01:00", 2) == [
            "2026-03-29 03:30 CEST",
            "2026-03-30 02:30 CEST",
        ]
        # An hourly one reads the wall clock too: the repeated 02:30 is not a launch of its own.
        assert _walk("Hourly", "00:30", "", "2026-10-25T00:00:00+02:00", 5) == [
            "2026-10-25 00:30 CEST",
            "2026-10-25 01:30 CEST",
            "2026-10-25 02:30 CEST",
            "2026-10-25 03:30 CET",
            "2026-10-25 04:30 CET",
        ]


@case
def weekly_and_monthly_schedules_walk_their_day_in_a_row():
    with _paris():
        assert _walk("Weekly", "09:00", "Monday", "2026-10-14T12:00:00+02:00", 3) == [
            "2026-10-19 09:00 CEST",
            "2026-10-26 09:00 CET",
            "2026-11-02 09:00 CET",
        ]
        assert _walk("Monthly", "07:00", "31", "2027-01-01T00:00:00+01:00", 3) == [
            "2027-01-31 07:00 CET",
            "2027-02-28 07:00 CET",
            "2027-03-31 07:00 CEST",
        ]


@case
def a_paused_or_unreadable_schedule_has_no_upcoming_moment():
    """The calendar draws from `upcoming`: a schedule that is off is a schedule nothing is due from."""
    now = datetime.fromisoformat("2026-10-14T21:00:00+02:00")
    page = store.Page(id="a" * 32, title="Whisper Desk", properties={}, url="")
    due = schedules.Schedule(
        page=page, name="Whisper Desk", cadence="Daily", at="09:00", day="", active=True,
        next=datetime.fromisoformat("2026-10-09T09:00:00+02:00"), last=None,
        last_ticket="", project="", model="", priority="",
    )
    assert schedules.upcoming(due, now) == now, "due: it fires on the next pass, never in the past"
    due.active = False
    assert schedules.upcoming(due, now) is None
    due.active, due.problem = True, "no cadence the runner knows"
    assert schedules.upcoming(due, now) is None


@case
def a_date_range_schedules_on_its_end():
    """Notion dates may be ranges; the runner reads the moment work is due."""
    page = notion.Page(
        id="x", url="u", title="t",
        properties={
            "Due": {"type": "date", "date": {"start": "2026-08-30", "end": "2026-09-02"}},
            "Single": {"type": "date", "date": {"start": "2026-08-30", "end": None}},
            "Empty": {"type": "date", "date": None},
        },
    )
    assert notion.read(page, "Due") == "2026-09-02"
    assert notion.read(page, "Single") == "2026-08-30"
    assert notion.read(page, "Empty") is None


# -- what comes back on its own ----------------------------------------------


def _after(text: str) -> datetime:
    """A naive local moment to compute the next occurrence from."""
    return datetime.fromisoformat(text)


@case
def each_cadence_lands_on_the_first_moment_after_now():
    """The four cadences, read against a Wednesday afternoon."""
    now = _after("2026-09-09T14:20:00")  # a Wednesday

    hourly = schedules.next_occurrence("Hourly", "09:35", after=now)
    assert hourly == _after("2026-09-09T14:35:00")
    # An empty hour means the top of the hour, not nine in the morning.
    assert schedules.next_occurrence("Hourly", "", after=now) == _after("2026-09-09T15:00:00")

    daily = schedules.next_occurrence("Daily", "09:00", after=now)
    assert daily == _after("2026-09-10T09:00:00"), "the hour is behind us: tomorrow"
    assert schedules.next_occurrence("Daily", "18:30", after=now) == _after("2026-09-09T18:30:00")

    weekly = schedules.next_occurrence("Weekly", "09:00", "Monday", after=now)
    assert weekly == _after("2026-09-14T09:00:00")
    # No day named: the weekday the schedule is read on, a week from now since
    # this Wednesday's nine o'clock has already gone.
    assert schedules.next_occurrence("Weekly", "09:00", after=now) == _after("2026-09-16T09:00:00")

    monthly = schedules.next_occurrence("Monthly", "08:00", "1", after=now)
    assert monthly == _after("2026-10-01T08:00:00")


@case
def a_monthly_schedule_on_the_31st_lands_on_the_last_day_february_has():
    """Seven months have a 31st. A schedule set on it does not skip the others."""
    from_january = schedules.next_occurrence(
        "Monthly", "07:00", "31", after=_after("2026-01-31T09:00:00")
    )
    assert from_january == _after("2026-02-28T07:00:00")
    leap = schedules.next_occurrence(
        "Monthly", "07:00", "31", after=_after("2028-01-31T09:00:00")
    )
    assert leap == _after("2028-02-29T07:00:00")


@case
def an_occurrence_is_always_strictly_after_the_moment_it_is_computed_from():
    """Landing *on* `after` would have a pass fire the same occurrence twice."""
    exactly = _after("2026-09-09T09:00:00")
    assert schedules.next_occurrence("Daily", "09:00", after=exactly) == _after(
        "2026-09-10T09:00:00"
    )
    assert schedules.next_occurrence("Hourly", "00", after=exactly) == _after(
        "2026-09-09T10:00:00"
    )


@case
def a_schedule_nobody_can_read_is_none_rather_than_an_exception():
    now = _after("2026-09-09T14:20:00")
    assert schedules.next_occurrence("Fortnightly", "09:00", after=now) is None
    assert schedules.next_occurrence("", "09:00", after=now) is None
    assert schedules.next_occurrence("Daily", "bientôt", after=now) is None
    assert schedules.next_occurrence("Daily", "31:00", after=now) is None
    assert schedules.next_occurrence("Weekly", "09:00", "Lunedì", after=now) is None
    assert schedules.next_occurrence("Monthly", "09:00", "quarante", after=now) is None
    # And an aware moment comes back aware, in this machine's timezone: the same
    # reading `scheduled_for` gives a date written on a ticket.
    aware = schedules.next_occurrence("Daily", "09:00", after=now.astimezone())
    assert aware is not None and aware.tzinfo is not None


def _schedule_page(page_id: str, **values) -> notion.Page:
    """One row of the Schedules database, as Notion hands it over."""
    last_ticket = values.get("last_ticket", "")
    return notion.Page(
        id=page_id,
        url=f"https://notion.so/{page_id}",
        title=values.get("name", "Revue des dépendances"),
        properties={
            "Cadence": {"type": "select", "select": {"name": values.get("cadence", "Daily")}},
            "At": {"type": "rich_text",
                   "rich_text": [{"plain_text": values.get("at", "09:00")}]},
            "Day": {"type": "rich_text", "rich_text": [{"plain_text": values.get("day", "")}]},
            "Active": {"type": "checkbox", "checkbox": values.get("active", True)},
            "Next": {"type": "date",
                     "date": {"start": values["next"]} if values.get("next") else None},
            "Last": {"type": "date", "date": None},
            "Last ticket": {"type": "relation",
                            "relation": [{"id": last_ticket}] if last_ticket else []},
            "Project": {"type": "relation", "relation": [{"id": "p-animalink"}]},
            "Priority": {"type": "number", "number": 40},
            **({"Type": {"type": "select", "select": {"name": values["type"]}}}
               if values.get("type") else {}),
            **({"Sous-type": {"type": "select", "select": {"name": values["subtype"]}}}
               if values.get("subtype") else {}),
            **({"Model": {"type": "select", "select": {"name": values["model"]}}}
               if values.get("model") else {}),
        },
    )


class _ScheduleClient:
    """A schedules database, a tickets database, and nothing that reaches out."""

    def __init__(self, pages, tickets=None, refuses=""):
        self._pages = pages
        self._tickets = tickets or {}
        self._refuses = refuses
        self.written: list[tuple[str, dict]] = []
        self.created: list[tuple[str, dict]] = []
        self.appended: list[tuple[str, str]] = []

    def schema(self, database_id):
        return {"Status": "status"}

    def query(self, database_id, filter_=None):
        return list(self._pages)

    def page(self, page_id):
        if page_id in self._tickets:
            return self._tickets[page_id]
        raise notion.NotionError(f"{page_id}: object not found")

    def update(self, database_id, page_id, values):
        self.written.append((page_id, dict(values)))

    def create_row(self, database_id, title, values=None):
        if self._refuses:
            raise notion.NotionError(self._refuses)
        self.created.append((title, dict(values or {})))
        return f"t-{len(self.created)}"

    def blocks_text(self, block_id, depth=0, *, live=True):
        return "Lister les dépendances en retard, et dire lesquelles comptent."

    def append_markdown(self, page_id, markdown):
        self.appended.append((page_id, markdown))
        return 1


def _recurring(pages, *, tickets=None, refuses="", schedule=True, dry_run=False) -> Runner:
    """A Runner with nothing underneath it but a schedules database."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = _ScheduleClient(pages, tickets, refuses)
    runner.config = C.Config(
        notion=C.Notion(properties=dict(C._DEFAULT_PROPERTIES), status={}),
        runner=C.Runner(schedule=schedule),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db-tickets", schedules="db-schedules")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner.dry_run = dry_run
    return runner


def _ticket_page(page_id: str, status: str) -> notion.Page:
    return notion.Page(
        id=page_id, url="", title=page_id,
        properties={"Status": {"type": "status", "status": {"name": status}}},
    )


def _written(client, name: str) -> object:
    """The last value written into one column of the schedule, or None."""
    for _, values in reversed(client.written):
        if name in values:
            return values[name]
    return None


@case
def a_machine_that_was_off_for_three_days_produces_one_ticket_and_not_twelve():
    """Anacron, not cron: waking up must not set off an avalanche of sessions."""
    stale = (datetime.now().astimezone() - timedelta(days=3)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    born = runner.recur()

    assert len(born) == 1 and born[0]["status"] == "scheduled"
    assert born[0]["from"] == "Revue des dépendances"
    assert len(runner.client.created) == 1, "one ticket, not one per day missed"
    title_, values = runner.client.created[0]
    assert title_.startswith("Revue des dépendances — ")
    assert values["Status"] == "Ready"
    assert values["Project"] == "p-animalink" and values["Priority"] == 40

    # The next moment is computed from now, never by stacking up what was lost.
    ahead = schedules.scheduled_for(_written(runner.client, "Next"))
    assert ahead is not None and ahead > datetime.now().astimezone()
    assert ahead < datetime.now().astimezone() + timedelta(days=1), "the next one, not the fourth"


@case
def a_code_schedule_makes_a_code_ticket_that_nobody_classifies():
    """A long, well-written brief read as « Rédaction » by the classifier sent
    four Whisper Desk tickets to done with their pull requests lost: the
    schedule says what its tickets are, and the ticket is born with it."""
    stale = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    runner = _recurring([_schedule_page(
        "s-1", next=stale, type="Code", subtype="Feature", model="opus"
    )])
    assert len(runner.recur()) == 1
    _, values = runner.client.created[0]
    assert values["Type"] == "Code" and values["Sous-type"] == "Feature"
    assert values["Model"] == "opus" and values["Priority"] == 40

    # Born typed, it is never handed to the classifier.
    born = notion.Page(id="t-1", url="", title="Revue — 2026-10-16", properties={
        "Type": {"type": "select", "select": {"name": values["Type"]}},
        "Sous-type": {"type": "select", "select": {"name": values["Sous-type"]}},
    })
    runner.client.schema = lambda database_id: {"Status": "status", "Type": "select",
                                                "Sous-type": "select"}

    def classified(*_):
        raise AssertionError("a typed ticket is not classified")

    runner._classify = classified
    runner._ask_subtype = classified
    assert runner._kind(ticket_module.Ticket(born), "", projects.Project(name="", path=None)) == ("code", "")
    assert runner._subtype(ticket_module.Ticket(born), "") == ("feature", "")


@case
def a_schedule_without_a_type_leaves_its_ticket_to_be_classified():
    stale = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    runner.recur()
    _, values = runner.client.created[0]
    assert "Type" not in values and "Sous-type" not in values


@case
def launching_a_schedule_by_hand_makes_the_ticket_and_leaves_its_next_moment_alone():
    """Even paused: that is how one is tried. `Last` moves, `Next` does not."""
    later = (datetime.now().astimezone() + timedelta(days=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=later, active=False)])
    recorded: list[dict] = []
    original = state.record
    state.record = recorded.append
    try:
        entry = runner.launch("s-1")
    finally:
        state.record = original

    assert len(runner.client.created) == 1 and entry["id"] == "t1"
    assert runner.client.created[0][1]["Status"] == "Ready"
    assert _written(runner.client, "Last") is not None
    assert _written(runner.client, "Next") is None, "the planned occurrence is untouched"
    assert _written(runner.client, "Active") is None, "a paused schedule stays paused"
    assert recorded and recorded[0]["status"] == "scheduled"


@case
def a_launch_that_fails_is_raised_and_leaves_last_alone():
    runner = _recurring([_schedule_page("s-1")], refuses="400 body failed validation")
    try:
        runner.launch("s-1")
    except notion.NotionError:
        pass
    else:
        raise AssertionError("the failure has to reach whoever asked")
    assert _written(runner.client, "Last") is None


@case
def the_body_of_the_schedule_is_copied_into_the_ticket_it_makes():
    """The ticket has to read on its own, and say where it came from."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    runner.recur()

    page_id, body = runner.client.appended[0]
    assert page_id == "t-1"
    assert "Revue des dépendances" in body and "https://notion.so/s-1" in body
    assert "Lister les dépendances en retard" in body
    # And the schedule is told what it produced, which is how the next pass
    # knows whether this occurrence is over.
    assert _written(runner.client, "Last ticket") == "t-1"


@case
def an_occurrence_still_open_never_produces_a_second_one():
    """A schedule stuck on a question must not fill the board with copies."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    for status in ("Ready", "In progress", "In review", "Blocked"):
        runner = _recurring(
            [_schedule_page("s-1", next=stale, last_ticket="t-old")],
            tickets={"t-old": _ticket_page("t-old", status)},
        )
        assert runner.recur() == [], status
        assert runner.client.created == [], status
        # Next moves on regardless, or the schedule would keep re-firing.
        ahead = schedules.scheduled_for(_written(runner.client, "Next"))
        assert ahead is not None and ahead > datetime.now().astimezone(), status

    for status in ("Done", "Failed"):
        runner = _recurring(
            [_schedule_page("s-1", next=stale, last_ticket="t-old")],
            tickets={"t-old": _ticket_page("t-old", status)},
        )
        assert len(runner.recur()) == 1, status


@case
def a_last_ticket_that_no_longer_exists_never_wedges_its_schedule():
    """A page somebody deleted would otherwise stop it being born for good."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale, last_ticket="t-gone")])
    assert len(runner.recur()) == 1


@case
def a_schedule_written_this_minute_does_not_fire_this_minute():
    """“Weekly / Monday” written on a Tuesday must not produce a ticket now."""
    runner = _recurring([_schedule_page("s-1", cadence="Weekly", day="Monday", next="")])
    assert runner.recur() == []
    assert runner.client.created == []
    ahead = schedules.scheduled_for(_written(runner.client, "Next"))
    assert ahead is not None and ahead > datetime.now().astimezone()
    assert _written(runner.client, "Last") is None, "nothing happened, so nothing was the last"


@case
def a_schedule_in_the_future_and_one_that_is_off_both_cost_nothing():
    later = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()

    ahead = _recurring([_schedule_page("s-1", next=later)])
    assert ahead.recur() == [] and ahead.client.written == []

    unticked = _recurring([_schedule_page("s-1", next=stale, active=False)])
    assert unticked.recur() == [] and unticked.client.written == []

    # One line turns every schedule off, without unticking a single row — and
    # without the database being read at all.
    off = _recurring([_schedule_page("s-1", next=stale)], schedule=False)
    assert off.recur() == [] and off.client.written == []

    # A schedule nobody can read holds nobody up.
    broken = _recurring([
        _schedule_page("s-broken", cadence="Fortnightly", next=stale),
        _schedule_page("s-fine", next=stale),
    ])
    assert len(broken.recur()) == 1
    assert broken.client.created[0][0].startswith("Revue")


@case
def a_dry_run_says_what_would_be_born_and_writes_nowhere():
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], dry_run=True)
    born = runner.recur()
    assert len(born) == 1 and born[0]["status"] == "dry-run"
    assert runner.client.created == [] and runner.client.written == []


@case
def the_occurrence_is_taken_before_it_is_made():
    """A crash between the two loses one occurrence; the other order makes two.

    So a ticket Notion refuses still leaves `Next` moved on: one lost report
    beats two identical tickets and the session each of them costs.
    """
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], refuses="400 body failed validation")
    assert runner.recur() == []
    ahead = schedules.scheduled_for(_written(runner.client, "Next"))
    assert ahead is not None and ahead > datetime.now().astimezone()
    assert _written(runner.client, "Last ticket") is None, "nothing was made to point at"


@case
def a_workspace_with_nothing_that_repeats_is_a_workspace_that_runs():
    """The whole feature is optional: no row, no warning, no difference."""
    client = _FakeClient({"Tickets": "p-tickets", "Context": "p-context"}, text="x")
    space = workspace.from_notion(client, _settings())
    assert space.schedules == ""
    assert not space.warnings

    present = _FakeClient(
        {"Tickets": "p-tickets", "Context": "p-context", "Schedules": "p-schedules"}, text="x"
    )
    assert workspace.from_notion(present, _settings()).schedules == "db-of-p-schedules"

    # And a Runner reading a workspace without one asks Notion nothing at all.
    runner = _recurring([])
    runner._workspace = workspace.Workspace(tickets="db-tickets")
    assert runner.recur() == [] and runner.schedules() == []


@case
def the_schedules_database_is_built_after_the_tickets_it_points_at():
    """A relation cannot name a database that does not exist yet."""
    board = _Board()
    provision.provision(board, _settings(), "root")

    schema = board._schemas["db-schedules"]
    for expected in ("Cadence", "At", "Day", "Active", "Next", "Last", "Last ticket",
                     "Type", "Sous-type"):
        assert expected in schema, expected
    # The same options as the tickets', so a value copied across is one they offer.
    tickets = board._schemas["db-tickets"]
    for column in ("Type", "Sous-type"):
        assert schema[column] == tickets[column], column
    assert schema["Last ticket"]["relation"]["database_id"] == "db-tickets"
    assert schema["Project"]["relation"]["database_id"] == "db-projects"
    assert board.created.index("db-tickets") < board.created.index("db-schedules")

    cadences = [option["name"] for option in schema["Cadence"]["select"]["options"]]
    assert cadences == list(schedules.CADENCES)

    # The example schedule is left unticked: an init must start nothing.
    example = board._rows["db-schedules"]
    assert len(example) == 1
    row = provision.schedules_schema(_settings(), "db-tickets", "db-projects")
    assert len(row) == 13, "twelve columns beside the title"


@case
def init_run_again_on_a_board_that_already_schedules_touches_nothing():
    board = _Board()
    provision.provision(board, _settings(), "root")
    before = dict(board._schemas["db-schedules"])
    board.created.clear()

    second = provision.provision(board, _settings(), "root")
    assert board.created == [], "no second schedules database, no second example"
    assert board._schemas["db-schedules"] == before
    assert any("Schedules" in what for verb, what in second.steps if verb == "kept")
    assert all(verb == "kept" for verb, _ in second.steps), second.steps


# -- staying up to date ------------------------------------------------------


@contextmanager
def _state_home():
    """A throwaway XDG_STATE_HOME, for what the runner keeps between two runs."""
    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    try:
        yield Path(os.environ["XDG_STATE_HOME"]) / "ponos"
    finally:
        # Its database too: a connection left open per test is three file
        # descriptors, and the suite has hundreds of these.
        db.close()
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous


@case
def an_update_needs_both_sides_to_be_known():
    """A check that could not reach the remote must not look like a new version.

    Everything else here fails quietly, so `stale` is the one place where a
    missing answer would otherwise turn into a reinstall.
    """
    assert update.Status(current="a" * 40, latest="b" * 40).stale
    assert not update.Status(current="a" * 40, latest="a" * 40).stale
    assert not update.Status(current="a" * 40).stale
    assert not update.Status(reason="git fetch: could not resolve host").stale
    assert not update.Status().stale


@case
def the_check_is_hourly_rather_than_once_per_run():
    """At a ten-second cadence the difference is 360 git fetches an hour."""
    with _state_home():
        assert update.due(3600), "an installation never checked is due at once"
        update.remember(update.Status(current="a" * 40, latest="a" * 40))
        assert not update.due(3600), "and not again before the interval is out"
        assert update.due(0)
        assert update.last_check() > 0


@case
def a_stamp_that_cannot_be_read_makes_the_check_due():
    with _state_home() as state_home:
        state_home.mkdir(parents=True)
        (state_home / "update.json").write_text("half a line of jso")
        assert update.last_check() == 0.0
        assert update.due(3600)


@contextmanager
def _installation():
    """A remote and an installation cloned from it, as `install.sh` leaves one.

    Yields `commit(message, tag="")`, which lands a commit on the remote's
    `main` — tagged when asked — and the installation's directory.
    """
    quiet = {"capture_output": True, "check": True}
    who = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    with tempfile.TemporaryDirectory() as directory:
        remote, work, app = (Path(directory) / name for name in ("remote.git", "work", "app"))
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)], **quiet)
        subprocess.run(["git", "clone", "--quiet", str(remote), str(work)], **quiet)

        def commit(message: str, tag: str = "") -> str:
            subprocess.run(["git", *who, "-C", str(work), "commit", "--quiet", "--allow-empty",
                            "-m", message], **quiet)
            if tag:
                subprocess.run(["git", *who, "-C", str(work), "tag", "-a", tag, "-m", tag], **quiet)
            subprocess.run(["git", "-C", str(work), "push", "--quiet", "--follow-tags", "origin",
                            "HEAD:main"], **quiet)
            return subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()

        first = commit("one")
        subprocess.run(["git", "clone", "--quiet", str(remote), str(app)], **quiet)
        yield commit, app, first


@case
def an_installation_follows_releases_and_not_every_commit_of_main():
    """Every commit pushed to `main` used to run on every installation within
    the hour. The default now follows the newest `vX.Y.Z` tag — and with none,
    updates nothing and says why rather than falling back on `main`."""
    with _state_home(), _installation() as (commit, app, first):
        commit("two, merged but not released")
        status = update.check(app, "release")
        assert not status.stale, "no release, no update"
        assert "no release" in status.reason, status.reason

        released = commit("three", tag="v0.2.0")
        commit("four, not released yet")
        commit("a pre-release", tag="v0.3.0-rc1")
        status = update.check(app, "release")
        assert status.stale and status.latest == released and status.tag == "v0.2.0", status
        assert status.current == first

        followed = update.check(app, "main")
        assert followed.stale and followed.latest not in (released, first), "main is every commit"
        assert not followed.tag

        # Already past the release — a clone of main switched to the release
        # channel — is not taken back to it.
        subprocess.run(["git", "-C", str(app), "reset", "--quiet", "--hard", followed.latest],
                       capture_output=True, check=True)
        ahead = update.check(app, "release")
        assert not ahead.stale and not ahead.reason, ahead

    assert update.newest_release(["v0.9.0", "v0.10.0", "v0.10.0-rc2", "vnext", "v1"]) == "v0.10.0"
    assert update.newest_release([]) == ""


@case
def the_update_channel_is_release_unless_the_file_says_main():
    assert C.Runner().update_channel == "release"
    assert _config("[runner]\n").runner.update_channel == "release"
    assert _config('[runner]\nupdate_channel = "main"\n').runner.update_channel == "main"
    assert _config('[runner]\nupdate_channel = "Main"\n').runner.update_channel == "main"
    assert _config('[runner]\nupdate_channel = "nightly"\n').runner.update_channel == "release", (
        "a typo must not put an installation on every commit"
    )
    example = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    assert 'update_channel = "release"' in example


@case
def a_copy_is_told_apart_from_a_clone_before_anything_is_fetched():
    """An install made with TR_SRC has no remote: a reason, not a failure."""
    status = update._look(Path(tempfile.mkdtemp()))
    assert not status.stale and "copy" in status.reason


@case
def an_update_puts_the_console_on_the_code_it_just_installed():
    """A run ends and the next one is the new code; the console never ends.

    On 18 September 2026 the console had been up since the evening before,
    serving `web/static/` off the disk — five commits newer than the Python
    answering it. The project list drew, because that route was in both; opening
    a project answered `no such route: /api/projects/<id>`, and the page said
    only that the project could not be read.

    `try-restart`, so that an update never starts a console somebody stopped.
    """
    with _installable() as (commit, app, first):
        # A `systemctl` that only writes down what it was asked, on a PATH of the
        # installation's own: a test that reloads this machine's units is a test
        # gone somewhere it was never asked to go.
        asked = app.parent / "systemctl.log"
        (app.parent / "bin" / "systemctl").write_text(
            f'#!/bin/sh\necho "$@" >> {asked}\n'
        )
        (app.parent / "bin" / "systemctl").chmod(0o755)
        (app.parent / "bin" / "sh").symlink_to(shutil.which("sh") or "/bin/sh")
        commit("two")
        error = update.apply(update.check(app, "main"), 600, app)
        ran = asked.read_text().splitlines()

    assert error == "", error
    restarts = [line for line in ran if "ponos-web.service" in line]
    assert restarts, "the console is left running the code the update replaced"
    assert restarts[0] == "--user try-restart ponos-web.service", (
        "a plain restart would start a console somebody stopped on purpose"
    )
    assert ran.index(restarts[0]) > ran.index("--user daemon-reload"), (
        "the console is restarted before its unit is reloaded"
    )


@contextlib.contextmanager
def _installable():
    """An installation of this very runner, cloned from a remote of its own.

    Yields `(commit, app, first)`: `commit(message, change)` lands a commit on
    the remote after `change(work)` has edited its files. The launcher is
    written to a home of the test's own, and systemd is out of the PATH — an
    install that rewrote this machine's units would be a test gone too far.
    """
    quiet = {"capture_output": True, "check": True}
    who = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    kept = {name: os.environ.get(name) for name in ("HOME", "PATH")}
    with tempfile.TemporaryDirectory() as directory, _state_home():
        remote, work, app = (Path(directory) / name for name in ("remote.git", "work", "app"))
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)], **quiet)
        subprocess.run(["git", "clone", "--quiet", str(remote), str(work)], **quiet)
        ignore = shutil.ignore_patterns("__pycache__")
        for part in ("src", "bin", "systemd"):
            shutil.copytree(ROOT / part, work / part, ignore=ignore)

        def commit(message: str, change=lambda work: None) -> str:
            change(work)
            subprocess.run(["git", "-C", str(work), "add", "-A"], **quiet)
            subprocess.run(["git", *who, "-C", str(work), "commit", "--quiet", "--allow-empty",
                            "-m", message], **quiet)
            subprocess.run(["git", "-C", str(work), "push", "--quiet", "origin", "HEAD:main"], **quiet)
            return subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()

        first = commit("one")
        subprocess.run(["git", "clone", "--quiet", str(remote), str(app)], **quiet)
        # git and nothing else on the PATH: no systemctl to reload this machine's units with.
        tools = Path(directory) / "bin"
        tools.mkdir()
        (tools / "git").symlink_to(shutil.which("git") or "/usr/bin/git")
        os.environ["HOME"], os.environ["PATH"] = directory, str(tools)
        try:
            yield commit, app, first
        finally:
            for name, value in kept.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _head(app: Path) -> str:
    return subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


@case
def a_version_that_does_not_start_is_taken_back_and_one_that_does_is_kept():
    """An update is all of it or none of it.

    `git reset` was the whole update: a commit that failed at `import` would
    have been installed, and every run after it would have died before
    claiming a ticket — with nobody there, since the runner runs alone. The new
    code is started by a Python of its own first, and the installation goes
    back to the commit it replaced when it does not.
    """
    with _installable() as (commit, app, first):
        broken = commit("broken", lambda work: (work / "src/ponos/__main__.py").write_text(
            "this is not python\n"))
        status = update.check(app, "main")
        assert status.stale and status.latest == broken
        error = update.install(status, 600, app)
        assert error and "does not start" in error and f"still on {first[:8]}" in error, error
        assert _head(app) == first, "a version that does not start was left installed"
        assert update.waiting(app).stale, "the update is still to be made"
        assert app.is_symlink() and app.resolve().name == f"app-{first[:12]}", (
            "the installation was not given a directory per version"
        )
        assert not app.with_name(f"app-{broken[:12]}").exists(), "the broken version was kept"

        fixed = commit("fixed", lambda work: shutil.copy(
            ROOT / "src/ponos/__main__.py", work / "src/ponos/__main__.py"))
        status = update.check(app, "main")
        assert update.install(status, 600, app) == ""
        assert _head(app) == fixed
        assert app.resolve().name == f"app-{fixed[:12]}"
        # The version replaced is still whole on disk: what was started on it
        # keeps importing from it, and it is the one to go back to.
        previous = app.with_name(f"app-{first[:12]}")
        assert _head(previous) == first, "the previous version was written over"
        third = commit("three")
        assert update.install(update.check(app, "main"), 600, app) == ""
        assert _head(app) == third
        assert not previous.exists(), "every version ever installed is kept"
        assert _head(app.with_name(f"app-{fixed[:12]}")) == fixed, "the previous one is gone"
        launcher = Path(os.environ["HOME"]) / ".local/bin/ponos"
        assert str(app) in launcher.read_text(), "the launcher still points at the old sources"
        assert not update.waiting(app).stale, (
            "the header still offered the update it had just installed"
        )


@case
def the_header_does_not_offer_a_version_already_installed():
    """On 30 September 2026 the header said ↑ on an installation already on the
    newest commit: the stamp was written before the update it announced, and
    read for the hour after. What is on disk has the last word."""
    with _installable() as (commit, app, first):
        second = commit("two")
        update.remember(update.Status(current=first, latest=second))
        assert update.waiting(app).stale, "installed is what the stamp compared: an update"
        subprocess.run(["git", "-C", str(app), "pull", "--quiet", "origin", "main"],
                       capture_output=True, check=True)
        assert not update.waiting(app).stale, "moved by hand since the check: nothing to offer"
    page = "https://github.com/owner/repo"
    tagged = update.Status(current="a" * 40, latest="b" * 40, tag="v0.2.0")
    assert update.notes(tagged, page) == f"{page}/releases/tag/v0.2.0"
    assert update.notes(update.Status(current="a" * 40, latest="b" * 40), page) == (
        f"{page}/compare/{'a' * 12}...{'b' * 12}"
    )
    assert update.notes(update.Status(current="a" * 40, latest="a" * 40), page) == ""


@case
def a_waiting_update_says_how_many_commits_it_brings_and_which():
    """The button carries a number and its tooltip the subjects: read at the
    check, from the clone that has just fetched, and kept in the stamp."""
    with _installable() as (commit, app, first):
        commit("two")
        commit("three")
        status = update.check(app, "main")
        assert status.behind == 2 and status.commits == ["three", "two"], status
        assert update.waiting(app).behind == 2, "the count is not in the stamp"
        assert update.waiting(app).commits == ["three", "two"]


@case
def the_console_looks_for_an_update_without_moving_the_run_s_clock():
    """A run checks once its interval has passed since the last check. The
    console looking every quarter of an hour must not count as one — or a run
    would never find its own due again, and never install anything."""
    from ponos.web import upgrade as web_upgrade

    with _installable() as (commit, app, first):
        update.remember(update.Status(current=first, latest=first))
        checked = update.last_check()
        second = commit("two")
        said: list[dict] = []
        upgrade = web_upgrade.Upgrade(
            lambda kind, **payload: said.append(payload), lambda: C.Runner(update_channel="main"), app=app
        )
        upgrade.look()
        assert update.last_check() == checked, "the console's look moved the run's clock"
        assert said and said[-1]["available"] and said[-1]["latest"] == second[:8]
        assert said[-1]["behind"] == 1 and said[-1]["commits"] == ["two"]
        upgrade.look()
        assert len(said) == 1, "nothing changed, and the pages were told again"

        commit("three")
        off = web_upgrade.Upgrade(
            lambda kind, **payload: said.append(payload), lambda: C.Runner(auto_update=False, update_channel="main"), app=app
        )
        off.look()
        assert len(said) == 1 and update.waiting(app).behind == 1, (
            "runner.auto_update = false, and the console fetched anyway"
        )


class _FakeUpdate:
    """`update`, as `web.upgrade` uses it: what is waiting, and what installing did."""

    def __init__(self, error: str = "") -> None:
        self.error = error
        self.installed: list[str] = []
        self.status = update.Status(current="a" * 40, latest="b" * 40)

    def __enter__(self):
        from ponos.web import upgrade as web_upgrade

        self.module = web_upgrade.update_module
        self.kept = {name: getattr(self.module, name) for name in ("waiting", "check", "install")}
        self.module.waiting = lambda app=None: self.status
        self.module.check = lambda app=None, channel="release": self.status
        self.module.install = lambda status, interval, app=None: (
            self.installed.append(status.latest) or self.error
        )
        return self

    def __exit__(self, *_):
        for name, value in self.kept.items():
            setattr(self.module, name, value)


def _until(condition, seconds: float = 5.0) -> None:
    deadline = time.time() + seconds
    while not condition():
        if time.time() > deadline:
            raise AssertionError("waited in vain")
        time.sleep(0.02)


@case
def an_update_from_the_console_waits_for_the_ticket_in_flight():
    """A click while a ticket runs is queued behind the run lock, never under it.

    Every session a ticket starts runs inside a pass that holds the lock; the
    update takes the same lock, so nothing is swapped while one runs, and the
    timer's next pass finds it busy and claims nothing. Called off while it
    waits, nothing is installed; a chat turn is waited for as well.
    """
    from ponos.web import upgrade as web_upgrade

    with _state_home(), _FakeUpdate() as fake:
        said: list[dict] = []
        restarted: list[int] = []
        talking = {"now": "a conversation turn is being answered"}
        upgrade = web_upgrade.Upgrade(
            lambda kind, **payload: said.append(payload), C.Runner, lambda: talking["now"],
            app=Path(tempfile.mkdtemp()), reboot=lambda: restarted.append(1), poll=0.02,
        )
        with state.lock():
            upgrade.start()
            _until(lambda: upgrade.detail == "a conversation turn is being answered")
            talking["now"] = ""
            _until(lambda: upgrade.detail == "a ticket is running")
            assert upgrade.phase == "waiting" and not fake.installed, "installed under a run"
            try:
                upgrade.start()
            except RuntimeError:
                pass
            else:
                raise AssertionError("two updates at once")
        _until(lambda: restarted)
        assert fake.installed == ["b" * 40]
        assert upgrade.phase == "restarting"
        phases = [payload["phase"] for payload in said]
        assert phases.index("installing") > phases.index("waiting")
        assert phases[-1] == "restarting"
        # The process that comes back knows what it came back from.
        again = web_upgrade.Upgrade(lambda kind, **payload: None, C.Runner, app=upgrade.app)
        assert again.phase == "done" and again.target == "b" * 8

        # Called off while it waits: nothing installed, nothing restarted. (The
        # restart above was a function: a real one would have ended this process.)
        upgrade.phase = "idle"
        fake.installed.clear()
        restarted.clear()
        with state.lock():
            upgrade.start()
            _until(lambda: upgrade.detail == "a ticket is running")
            upgrade.cancel()
            _until(lambda: upgrade.phase == "idle")
        time.sleep(0.1)
        assert not fake.installed and not restarted


@case
def a_failed_update_from_the_console_says_why_and_restarts_nothing():
    from ponos.web import upgrade as web_upgrade

    with _state_home(), _FakeUpdate("the new version does not start: boom — back on aaaaaaaa"):
        restarted: list[int] = []
        upgrade = web_upgrade.Upgrade(
            lambda kind, **payload: None, C.Runner,
            app=Path(tempfile.mkdtemp()), reboot=lambda: restarted.append(1), poll=0.02,
        )
        upgrade.start()
        _until(lambda: upgrade.phase == "failed")
        assert "back on aaaaaaaa" in upgrade.error
        assert any("failed:" in line for line in upgrade.progress()["log"])
        assert "failed:" in web_upgrade.log_path().read_text(encoding="utf-8"), "no log to read"
        assert not restarted, "the console was restarted onto a version that was taken back"
        offer = upgrade.offer(local=False)
        assert offer["available"] and not offer["automatic"] and offer["command"] == "ponos update"


@case
def the_update_endpoint_answers_only_this_machine_and_the_console_page():
    """The one write that replaces the code answering it: loopback, the guard
    header, and an `Origin` that is the console's own — and a body that
    chooses nothing."""
    import urllib.error
    import urllib.request

    from ponos.web import server as web_server

    started: list[int] = []

    class Upgrade:
        def start(self):
            started.append(1)
            return {"phase": "waiting"}

        def cancel(self):
            raise RuntimeError("the update is no longer waiting")

    api = _bare_api(_TalkClient([]))
    api._upgrade = Upgrade()
    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def post(path: str, **headers: str):
        sent = {"Authorization": "Bearer tok", "Content-Type": "application/json", **headers}
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=b'{"command": "rm -rf ~"}', headers=sent,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    guard = {"X-Ponos": "1"}
    try:
        assert post("/api/update") == 403, "a form posted from another page"
        assert post("/api/update", Origin="http://evil.example", **guard) == 403
        assert not started
        assert post("/api/update", Origin=f"http://127.0.0.1:{port}", **guard) == 200
        assert post("/api/update", **guard) == 200, "a script with the token sends no Origin"
        assert post("/api/update/cancel", **guard) == 409
    finally:
        console.shutdown()
        console.server_close()
    assert len(started) == 2

    handler = web_server.Handler.__new__(web_server.Handler)
    for address, local in (("127.0.0.1", True), ("::1", True), ("192.168.1.20", False),
                           ("100.64.0.3", False)):
        handler.client_address = (address, 0)
        assert handler._local() is local, address


# -- staying alive -----------------------------------------------------------


@case
def a_lock_left_by_a_dead_run_is_not_a_run():
    """`run.lock` on disk is what a killed run leaves behind; the flock is not.

    For two hours on 7 September 2026, `status` read the leftover file as a run
    in progress, and the search for the silence went the wrong way.
    """
    with _state_home() as state_home:
        state_home.mkdir(parents=True)
        (state_home / "run.lock").write_text("4242 2026-09-07T11:57:17+00:00\n")
        assert state.running() == "", "a file nobody holds is not a run"
        with state.lock():
            assert state.running().startswith(str(os.getpid())), "a held lock is one"
        assert state.running() == ""


@case
def a_run_turned_away_leaves_the_lock_and_its_holder_alone():
    """The lock file is one inode for good, and its PID survives a refusal.

    Unlinking it on release let a run waiting on the old inode and a run that
    created a new one both hold "the" lock. And `open("w")` emptied the file
    before asking for the lock — so a run turned away as busy had erased the
    name of the run that turned it away.
    """
    with _state_home() as state_home:
        path = state_home / "run.lock"
        with state.lock():
            inode = path.stat().st_ino
            try:
                with state.lock():
                    raise AssertionError("two runs held the lock at once")
            except state.Busy:
                pass
            assert path.read_text().startswith(f"{os.getpid()} "), "the holder is still named"
            assert state.running().startswith(str(os.getpid()))
        assert path.exists(), "the lock file is never removed"
        assert path.stat().st_ino == inode, "and never replaced"
        assert path.read_text() == "", "nobody is named once the lock is let go of"
        assert path.stat().st_mode & 0o777 == 0o600
        with state.lock():
            assert path.stat().st_ino == inode
            assert path.read_text().count("\n") == 1, "one holder, written once"


@case
def a_copy_of_a_secret_is_private_before_it_holds_anything():
    """The console's token, and the copies a save makes of the configuration.

    Written with the umask and tightened with `chmod` afterwards, each was
    readable by the group for the moment in between — the configuration holds
    the Notion token, the bot tokens and the console's password.
    """
    from ponos import disk
    from ponos.web import server as web_server

    created: list[tuple[str, int]] = []
    original = disk.os.open

    def spying(path, flags, mode=0o777, *rest, **kept):
        if flags & os.O_CREAT:
            created.append((str(path), mode))
        return original(path, flags, mode, *rest, **kept)

    previous = os.umask(0o022)
    disk.os.open = spying
    try:
        with _state_home():
            path = Path(tempfile.mkdtemp()) / "config.toml"
            path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n')
            path.chmod(0o600)
            C.edit(path, [("runner", "model", "opus")])
            secret = web_server.token(C.load(path))
            kept = web_server.token_path()
            assert kept.read_text().strip() == secret
            assert kept.stat().st_mode & 0o777 == 0o600
            backup = path.parent / "config.toml.bak"
            assert backup.stat().st_mode & 0o777 == 0o600
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        disk.os.open = original
        os.umask(previous)
    names = {Path(name).name: mode for name, mode in created}
    assert names.get("token") == 0o600, names
    assert names.get("config.toml.bak") == 0o600, names
    assert any(name.startswith(".config.toml.saving") and mode == 0o600 for name, mode in names.items()), names


@case
def a_claim_is_written_whole_or_not_at_all():
    """A crash halfway through a write must leave the claims as they were.

    A lost claim reads as "no claim", and a validated ticket without its claim
    comes back from a crash as work to redo. And two publications of one pass
    claim side by side: neither may lose the other's.
    """
    with _state_home():
        try:
            state.claim("a" * 32, "Validated")
            try:
                with db.transaction() as connection:
                    connection.execute("DELETE FROM claims")
                    connection.execute("INSERT INTO claims VALUES (?, ?)", ("b" * 32, "Ready"))
                    raise OSError("disk full")
            except OSError:
                pass
            assert state.claims() == {"a" * 32: "Validated"}, "the old claims are intact"
            workers = [
                threading.Thread(target=state.claim, args=(f"{n:032d}", "Ready")) for n in range(8)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            assert len(state.claims()) == 9, state.claims()
            state.release("a" * 32)
            assert "a" * 32 not in state.claims()
            assert db.path().stat().st_mode & 0o777 == 0o600
        finally:
            db.close()


@case
def what_a_session_said_is_kept_for_this_account_only():
    """Transcripts and the history carry briefs, code and whatever was printed."""
    with _state_home():
        previous = os.umask(0o022)
        try:
            state.record({"ticket": "t", "status": "done"})
            logs = state.logs_dir()
        finally:
            os.umask(previous)
        assert db.path().stat().st_mode & 0o777 == 0o600
        assert logs.stat().st_mode & 0o777 == 0o700


@case
def a_timer_with_no_next_run_is_stalled_rather_than_enabled():
    """What the incident's timer answered, and what a healthy one answers."""
    starved = systemd.describe(
        "enabled",
        "SubState=elapsed\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=infinity\n",
        "NEXT LEFT LAST PASSED UNIT ACTIVATES\n- - Mon 2026-09-07 13:57:17 CEST 2h ago ponos.timer ponos.service\n",
    )
    assert starved.stalled and starved.label == "stalled"
    assert starved.row.startswith("- -"), "the list-timers line travels with the verdict"

    armed = systemd.describe(
        "enabled", "SubState=waiting\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=18h 48min\n"
    )
    assert armed.armed and not armed.stalled and armed.label == "enabled"

    busy = systemd.describe(
        "enabled", "SubState=running\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=\n"
    )
    assert busy.running and not busy.stalled, "no next run while the service runs is a run"

    off = systemd.describe("disabled", "SubState=dead\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=\n")
    assert not off.stalled and off.label == "disabled", "only an enabled timer can lie"
    assert systemd.describe("", "").label == "", "and what is not installed says so as it did"


@case
def the_timer_counts_from_its_own_start():
    """OnBootSec serves once; OnUnitActiveSec needs a service that ran. A timer
    restarted after a failed run had neither, and never fired again."""
    previous = os.environ.get("HOME")
    os.environ["HOME"] = tempfile.mkdtemp()
    try:
        units = update.write_units(600, ROOT)
    finally:
        os.environ["HOME"] = previous
    timer = (units / "ponos.timer").read_text()
    for directive in ("OnActiveSec=600s", "OnBootSec=600s", "OnUnitActiveSec=600s"):
        assert directive in timer, directive
    assert "@" not in timer, "a placeholder left in the unit"


# -- when the credits run out -------------------------------------------------


@case
def an_exhausted_quota_is_told_apart_from_every_other_failure():
    """The one refusal that is not the session's fault, read off what it said.

    A false positive here would put the runner to sleep for a quarter of an
    hour on an ordinary crash, so nothing but these two sentences counts.
    """
    assert credits.reached("Claude AI usage limit reached|1758031200") == 1758031200.0
    # A timestamp in milliseconds would otherwise be the year 57000: a runner
    # asleep for good, on a message whose format changed under it.
    far = credits.reached("Claude AI usage limit reached|1758031200000")
    assert far <= time.time() + credits.LONGEST_WAIT
    # No moment named: a short wait, and the next run asks again.
    blind = credits.reached("Claude usage limit reached. Your limit will reset at 10pm.")
    assert time.time() + credits.BLIND_WAIT - 5 < blind <= time.time() + credits.BLIND_WAIT
    assert credits.reached("API Error: Credit balance is too low") > 0
    assert credits.reached("claude exited with code 1") == 0.0
    assert credits.reached("the session was killed after 30 min") == 0.0
    assert credits.reached("") == 0.0


@case
def a_wait_outlives_the_run_that_wrote_it():
    """A run is a process the timer starts: what it learned only travels on disk."""
    with _state_home():
        assert credits.held() == 0.0, "nothing waited for until something says so"
        credits.hold(time.time() + 300)
        assert credits.held() > time.time(), "the next run finds it and stands down"
        # A moment that has passed is no wait at all — and `release` is what
        # removes the note, so the run that finds the credits back can say so.
        credits.hold(time.time() - 1)
        assert credits.held() == 0.0
        assert credits.release() and not credits.release()


def _spent(seconds_away: float = 300) -> session.Outcome:
    """What `session.run` hands back when the subscription's window is spent."""
    return session.Outcome(
        ok=False,
        blocked=False,
        session_id="s-1",
        summary="",
        log=Path("/dev/null"),
        error="Claude AI usage limit reached",
        exhausted=True,
        resets_at=time.time() + seconds_away,
    )


def _out_of_credit(page: notion.Page) -> Runner:
    """A board runner whose every session dies on the quota."""
    runner = _board_runner([page], {})
    runner.config.runner.auto_update = False
    runner._run_session = lambda job, template: _spent()
    return runner


def _doc_job(page: notion.Page) -> ticket_module.Job:
    return ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )


@case
def a_ticket_the_credits_ran_out_on_waits_for_credit_rather_than_failing():
    """Nothing was wrong with it: there was nothing left to work on it with.

    Failing it would cost the ticket twice — once for the quota, and once for
    the four hours nobody is there to put it back. Blocking it would cost the
    board instead: "Blocked" is the column that means *you* are needed, and a
    column that also means "come back at six" has stopped saying anything. So
    it goes back to Ready, where it came from, and the attribute is what says
    the credit is why it is sitting there.
    """
    page = _reviewed("p-doc", "In progress", None)
    runner = _out_of_credit(page)
    runner.client.waiting = True
    result = runner._execute_document(_doc_job(page))
    assert runner.client.written[0][1]["Status"] == "Ready", "back where it came from"
    assert runner.client.written[0][1]["Waiting for credit"] is True
    # The session goes on the page with it: it is what the pass that has credit
    # again picks the ticket back up by, rather than starting it over.
    assert runner.client.written[0][1]["Session"] == "s-1"
    assert result["status"] == "waiting", "neither done, nor failed, nor blocked"
    said = runner.client.comments_written[0]
    assert said.startswith("⏸️ Waiting — out of credit, back in “Ready” until "), said
    assert "?" not in said, "a wait asks nothing of anybody"


@case
def a_board_without_the_attribute_puts_the_ticket_back_and_says_nothing():
    """The property is added by `init`, and an old board has never had one.

    Until it is there, an exhausted quota does exactly what it did before the
    attribute existed: the ticket goes back to the column it was claimed from,
    with nothing on the board saying why.
    """
    page = _reviewed("p-doc", "In progress", None)
    runner = _out_of_credit(page)
    assert runner.client.waiting is False, "premise"
    runner._execute_document(_doc_job(page))
    assert runner.client.written[0][1]["Status"] == "Ready"
    assert "back in “Ready”" in runner.client.comments_written[0]
    assert runner.waiting_flag() == "", "nothing to tick, and nothing pretends there is"


def _that_failed(page: notion.Page, *, folded: bool) -> tuple[Runner, list[str], dict]:
    """A document ticket whose session stopped, run to its report."""
    runner = _board_runner([page], {})
    runner.config.runner.auto_update = False
    runner.config.runner.keep_worktree_on_failure = False

    def stopped(job, template):
        # Half an answer written, and then the session died: a failure rather
        # than a question, which is the road a trace is actually read on.
        (job.workdir / "ANSWER.md").write_text("La moitié d'une réponse.")
        return session.Outcome(
            ok=False, blocked=False, session_id="s-1", summary="",
            error="npm test exited 1", log=Path("/logs/x.jsonl"), seconds=90.0, turns=4,
        )

    runner._run_session = stopped
    filed: list[str] = []
    job = ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )
    if folded:
        job.live = type(
            "L", (), {"detail": lambda self, text: bool(filed.append(text)) or True}
        )()
    return runner, filed, runner._execute_document(job)


@case
def a_run_that_failed_says_what_to_do_and_folds_the_rest_into_the_page():
    """A report used to end on the session id, the log path and the directory
    to resume from — three lines of machinery pushed to a phone every time.

    They are not gone, they are folded: the block the run already wrote its
    steps into takes them, and the report spends its lines on the verdict.
    """
    runner, filed, result = _that_failed(_reviewed("p-doc", "In progress", None), folded=True)
    assert result["status"] == "failed"
    said = runner.client.comments_written[0]
    assert said.splitlines() == [
        "⚠️ Failed — The session did not make it to the end.",
        "npm test exited 1",
        "What it did is in the folded block at the bottom of the page.",
    ], said
    assert "claude --resume s-1" not in said
    assert filed == [
        "To pick the session back up: `claude --resume s-1`. Its log is `/logs/x.jsonl`."
    ]


@case
def a_ticket_whose_run_wrote_no_block_keeps_the_trace_under_its_verdict():
    """`runner.progress = false`, or a Notion that refused: the trace has
    nowhere to be folded into, so it stays where it can be read."""
    runner, filed, _ = _that_failed(_reviewed("p-none", "In progress", None), folded=False)
    said = runner.client.comments_written[0]
    assert filed == []
    assert said.endswith("Its log is `/logs/x.jsonl`.")
    assert said.startswith("⚠️ Failed — ")


def _answered_on(comments: list[str], answer: str, write: str) -> tuple[Runner, dict]:
    """A document ticket whose session said `answer` and left `write` in ANSWER.md."""
    from ponos import question

    page = _reviewed("p-doc", "In progress", None)
    runner = _board_runner([page], {"review": "In review", "done": "Done"})
    runner.client.append_markdown = lambda _page, _text: 2
    runner.config.runner.keep_worktree_on_failure = False

    def answered(job, template):
        if write:
            (job.workdir / "ANSWER.md").write_text(write)
        return session.Outcome(
            ok=False, blocked=True, session_id="s-1", summary=session._summary(answer),
            answer=answer, log=Path("/logs/x.jsonl"), question=question.parse(answer),
        )

    runner._run_session = answered
    job = _doc_job(page)
    job.comments = comments
    return runner, runner._execute_document(job)


def _session_log(*steps: tuple[str, str]) -> Path:
    """A session's stream-json log: each step a Bash command and what it printed."""
    log = Path(tempfile.mkdtemp()) / "s.jsonl"
    lines = []
    for number, (command, printed) in enumerate(steps):
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"u{number}", "name": "Bash", "input": {"command": command}}
        ]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"u{number}", "content": printed}
        ]}})
    log.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return log


@case
def a_pull_request_a_writing_session_opened_is_attached_and_sent_to_review():
    """Four Whisper Desk tickets classified « Rédaction » opened their pull
    requests themselves: done, an empty Pull Request column, nothing to review,
    and two of them doing the same thing. Never again a pull request lost."""
    url = "https://github.com/SalvadorCardona/whisper-desk/pull/21"
    page = _reviewed("p-doc", "In progress", None)
    runner = _board_runner([page], {"review": "In review", "done": "Done"})
    runner.client.append_markdown = lambda _page, _text: 2
    log = _session_log(
        ("git log --oneline -3", "abc fix: something https://github.com/x/y/pull/3"),
        ("gh pr create --title 'feat: Wispr Flow' --body x", f"Creating pull request\n{url}\n"),
    )

    def answered(job, template):
        (job.workdir / "ANSWER.md").write_text("Fait : la PR est ouverte.")
        return session.Outcome(ok=True, blocked=False, session_id="s-1", summary="ok",
                               answer="RESULT: ok — PR ouverte", log=log)

    runner._run_session = answered
    job = _doc_job(page)
    job.kind = "writing"
    runner._execute_document(job)
    values = runner.client.written[-1][1]
    assert values["Status"] == "In review", "in review, where a pull request waits"
    assert values["Pull Request"] == url, "the pull request is the ticket's"
    said = runner.client.comments_written[-1]
    assert url in said and "review" in said.lower(), said

    assert session.pull_requests(log) == [url], "only what `gh pr create` printed"


@case
def a_writing_session_that_opened_nothing_still_ends_in_done():
    page = _reviewed("p-doc", "In progress", None)
    runner = _board_runner([page], {"review": "In review", "done": "Done"})
    runner.client.append_markdown = lambda _page, _text: 2
    log = _session_log(("gh pr list", "https://github.com/x/y/pull/3\n"))

    def answered(job, template):
        (job.workdir / "ANSWER.md").write_text("Le texte.")
        return session.Outcome(ok=True, blocked=False, session_id="s-1", summary="ok",
                               answer="RESULT: ok — écrit", log=log)

    runner._run_session = answered
    job = _doc_job(page)
    job.kind = "writing"
    runner._execute_document(job)
    values = runner.client.written[-1][1]
    assert values["Status"] == "Done" and "Pull Request" not in values


@case
def a_log_event_whose_message_is_a_sentence_does_not_crash_the_ticket():
    """Opoil and Leadz Ninja, both transferred, both « le runner lui-même a
    cassé » : Claude in Chrome refused a browser-internal tab, and the
    `permission_denied` event it logs carries its `message` as a sentence, not
    as a dict. Reading the pull requests out of the log broke on it."""
    url = "https://github.com/SalvadorCardona/opoil/pull/4"
    log = _session_log(("gh pr create --title x --body y", f"{url}\n"))
    with log.open("a") as written:
        written.write(json.dumps({
            "type": "system", "subtype": "permission_denied",
            "tool_name": "mcp__claude-in-chrome__get_page_text",
            "message": "Can't interact with browser-internal or extension pages",
        }) + "\n")
        written.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "u9", "name": "Read", "input": "not a dict"},
        ]}}) + "\n")
    assert session.pull_requests(log) == [url]


@case
def a_question_answered_on_a_finished_ticket_goes_to_review_rather_than_blocked():
    """« C'est quoi X ? » — answered, nothing left to do, and said as a stop.

    No QUESTION written, so nothing to wait for: the ticket is read, not
    blocked again with its own answer as the reason.
    """
    with _state_home():
        runner, result = _answered_on(
            ["Salva: c'est quoi un CNAME ?"],
            "RESULT: blocked — un CNAME est un alias de nom de domaine",
            "Un CNAME est un alias.",
        )
    assert result["status"] == "done", result
    assert runner.client.written[-1][1]["Status"] == "In review", runner.client.written

    # A real question still blocks, and so does a stop with nothing written.
    with _state_home():
        _, asked = _answered_on(
            ["Salva: c'est quoi un CNAME ?"],
            "QUESTION: Je le crée chez OVH ?\nMODE: yes-no\nRESULT: blocked — où le créer ?",
            "Un CNAME est un alias.",
        )
        _, empty = _answered_on(["Salva: et alors ?"], "RESULT: blocked — je ne sais pas", "")
        _, unasked = _answered_on([], "RESULT: blocked — un CNAME est un alias", "Un alias.")
    assert asked["status"] == "blocked", asked
    assert empty["status"] == "blocked", empty
    assert unasked["status"] == "blocked", "nobody asked anything: a stop is a stop"


@case
def a_publication_the_credits_ran_out_on_goes_back_to_validated():
    """Not to ready: the decision to publish it has already been taken."""
    with _state_home():
        page = _reviewed("p-post", "Validated", None)
        runner = _out_of_credit(page)
        result = runner._publish(
            ticket_module.Ticket(page), projects.Project(name="", path=None)
        )
    assert runner.client.written[0][1]["Status"] == "In progress", "claimed first"
    assert runner.client.written[-1][1]["Status"] == "Validated"
    assert result["status"] == "waiting"
    assert state.claims() == {}, "and the claim is let go of on the way out"


@case
def nothing_at_all_is_run_while_the_credits_are_out():
    """Every session this pass could start would die on the same sentence."""
    with _state_home():
        runner = _out_of_credit(_reviewed("p-ready", "Ready", None))
        said: list[str] = []
        runner.quiet, runner.say, runner.announce_idle = False, said.append, True
        credits.hold(time.time() + 300)
        assert runner.tick() == []
        assert runner.client.queried == [], "the board is not even read"
        assert runner.client.written == []
        assert any("Out of credit" in line for line in said)

        # And the wait ends by itself: the run that finds it over says so, once.
        credits.hold(time.time() - 1)
        assert runner.waiting_for_credits() == 0.0
        assert any("credits are back" in line for line in said)


@case
def a_runner_told_not_to_wait_fails_on_the_quota_as_it_always_did():
    """`wait_for_credits = false` is the old behaviour, kept for an API key."""
    with _state_home():
        page = _reviewed("p-doc", "In progress", None)
        runner = _out_of_credit(page)
        runner.config.runner.wait_for_credits = False
        credits.hold(time.time() + 300)
        assert runner.waiting_for_credits() == 0.0, "a note nobody reads"

        job = ticket_module.Job(
            ticket_module.Ticket(page),
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )
        # Reported as the session failure it looks like — here a question, the
        # way a session that writes no answer always came back.
        assert runner._execute_document(job)["status"] == "blocked"
        assert "the credits are out" not in runner.client.comments_written[0]


# -- stopping short of the wall ------------------------------------------------


@contextmanager
def _usage(payload: object):
    """Claude Code's own store, replaced by what it would have cached.

    `payload` is what goes under `cachedUsageUtilization.utilization`; `None`
    writes no store at all, which is the reading nobody can take.
    """
    directory = Path(tempfile.mkdtemp())
    if payload is not None:
        (directory / ".claude.json").write_text(
            json.dumps({"cachedUsageUtilization": {"utilization": payload}}),
            encoding="utf-8",
        )
    previous = os.environ.get("CLAUDE_CONFIG_DIR")
    os.environ["CLAUDE_CONFIG_DIR"] = str(directory)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = previous


def _windows(session_percent: float, weekly: float = 0.0, hours: float = 4) -> dict:
    """The two windows `/usage` shows, as the cache holds them."""
    moment = datetime.now().astimezone() + timedelta(hours=hours)
    return {
        "five_hour": {"utilization": session_percent, "resets_at": moment.isoformat()},
        "seven_day": {"utilization": weekly, "resets_at": moment.isoformat()},
    }


@case
def the_most_constraining_of_the_two_windows_is_the_one_that_counts():
    """20 % of the week and 97 % of the session is 97 % spent, not 20 %."""
    with _usage(_windows(97, weekly=20)):
        used, until = credits.used()
        assert used == 97 and until > time.time()
    with _usage(_windows(3, weekly=88)):
        assert credits.used()[0] == 88

    # A window whose moment has passed rolled over after the cache was written,
    # so it is empty now whatever figure sits beside it — which is what makes a
    # stale cache safe to read rather than something to date-check.
    with _usage(_windows(99, weekly=99, hours=-2)):
        assert credits.used() == (0.0, 0.0)

    # And a reading is never invented: no store, no key, a shape that changed.
    with _usage(None):
        assert credits.used() is None
    with _usage({"five_hour": None, "seven_day": "?"}):
        assert credits.used() is None


def _reserving(pages: list[notion.Page], percent: int = 5) -> Runner:
    """A board runner with a reserve, whose sessions would all succeed."""
    runner = _board_runner(pages, {}, waiting=True)
    runner.config.runner.auto_update = False
    runner.config.runner.credit_reserve_percent = percent
    runner.config.runner.reply = False
    runner.announce_idle = False
    return runner


@case
def the_reserve_stops_the_runner_before_the_subscription_is_spent():
    """The whole point: a runner that spends the last of it is one you turn off.

    At 95 % nothing new is started — and the ticket that was ready says so on
    the board, ticked as waiting for credit, rather than sitting in a ready
    column that looks like a runner gone silent. It does not move: nothing
    happened to it, and it is still exactly as ready as it was.
    """
    started: list[str] = []
    with _state_home(), _usage(_windows(96)):
        runner = _reserving([_ready("p-1"), _ready("p-2")])
        runner.prepare = lambda ticket: started.append(ticket.id)
        results = runner.tick()

    assert started == [], "not one session begun"
    assert {page: values["Waiting for credit"] for page, values in runner.client.written} == {
        "p-1": True,
        "p-2": True,
    }
    assert all("Status" not in values for _, values in runner.client.written), "nothing moved"
    # The Session cell is emptied: nothing was started for these, so there is no
    # conversation to carry on — and a ticket woken by a comment must not have
    # the run before it resumed, arguing with its own verdict.
    assert all(values["Session"] == "" for _, values in runner.client.written)
    assert [result["status"] for result in results] == ["waiting", "waiting"]
    assert all("⏸️ Waiting" in said for said in runner.client.comments_written)


@case
def the_budget_limits_are_empty_unless_the_file_names_an_amount():
    assert _config("").budget == C.Budget(0.0, 0.0), "no table, no limit"
    assert _config('[budget]\ndaily_usd = ""\nper_ticket_usd = ""\n').budget == C.Budget(0.0, 0.0)
    assert _config("[budget]\ndaily_usd = 25\nper_ticket_usd = 2.5\n").budget == C.Budget(25.0, 2.5)
    assert _config('[budget]\ndaily_usd = -4\nper_ticket_usd = "n/a"\n').budget == C.Budget(0.0, 0.0)


@case
def the_daily_limit_holds_from_the_history_until_midnight_and_lifts_after():
    """Read off what the history says was spent today, and never before it is."""
    with _state_home():
        runner = _reserving([])
        assert runner.under_reserve() == 0.0, "no limit set"
        runner.config.budget.daily_usd = 5.0
        assert runner.under_reserve() == 0.0, "nothing spent yet"
        state.record({"id": "a", "status": "blocked", "cost_usd": 3.0})
        assert runner.under_reserve() == 0.0, "3 $ of 5 $"
        state.record({"id": "b", "status": "failed", "cost_usd": 2.0})
        until = runner.under_reserve()
        assert 0 < until - time.time() <= 24 * 3600, "held until the next midnight"
        assert credits.held(what="budget") == until
        runner.config.budget.daily_usd = 6.0
        assert runner.under_reserve() == 0.0, "a raised limit lifts it"
        assert not credits.held(what="budget"), "and the note goes with it"


@case
def a_reserve_of_ten_percent_stops_ten_percent_earlier():
    """The number is the setting's whole job, so it is the number that is read."""
    with _state_home(), _usage(_windows(92)):
        assert _reserving([], percent=5).under_reserve() == 0.0, "92 % is under 95 %"
        assert _reserving([], percent=10).under_reserve() > 0.0, "and over 90 %"

    # The wait ends when the constraining window does, not at some invented hour.
    with _state_home(), _usage(_windows(96, hours=3)):
        until = _reserving([], percent=5).under_reserve()
        assert 2.9 * 3600 < until - time.time() <= 3 * 3600


@case
def a_reserve_nobody_can_measure_changes_nothing_at_all():
    """A cache that is not there, or a shape that changed under us.

    Refusing to run on it would be the worse failure by some distance: the
    runner would stop working because it could not find a JSON key. So it says
    so once and behaves exactly as it did before the setting existed.
    """
    started: list[str] = []
    with _state_home(), _usage(None):
        runner = _reserving([_ready("p-1")])
        said: list[str] = []
        runner.quiet, runner.say = False, said.append
        runner.prepare = lambda ticket: started.append(ticket.id)
        runner.tick()

    assert started == ["p1"], "the ticket ran, as it always did"
    warnings = [line for line in said if "could not be read" in line]
    assert len(warnings) == 1, f"said once per run, not once per look: {warnings}"


@case
def the_reserve_is_read_again_at_every_free_place_not_once_a_pass():
    """A pass lasts as long as its longest session, and the sessions in flight
    are what fills the window: a pass that started under the line can cross it
    halfway through. What is running is left to finish — killing a session to
    save credit would spend what it has already cost.
    """
    finished = threading.Event()
    with _state_home(), _usage(_windows(10)) as _:
        runner = _reserving([_ready("p-1"), _ready("p-2")])
        runner.config.runner.max_concurrent = 1
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket, projects.Project(name="", path=None), branch="", base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            # The session itself is what spends the window, so the reading
            # changes underneath the pass rather than before it.
            store = Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".claude.json"
            store.write_text(
                json.dumps({"cachedUsageUtilization": {"utilization": _windows(98)}}),
                encoding="utf-8",
            )
            finished.set()
            return {"id": job.ticket.page.id, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert finished.is_set()
    assert [result["status"] for result in results] == ["done", "waiting"]
    assert results[1]["id"] == "p2", "the one it did not start says so on the board"


@case
def a_ticket_that_raises_fails_alone_and_the_pass_goes_on():
    """An exception out of one ticket used to come back out of `future.result()`
    and end the pass: the other sessions ran on unreported, and the ticket that
    raised sat in progress until a later sweep put it back — to raise again."""
    with _state_home(), _usage(_windows(10)):
        runner = _reserving([_ready("p-1"), _ready("p-2")])
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket, projects.Project(name="", path=None), branch="", base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            if job.ticket.id == "p1":
                raise subprocess.TimeoutExpired(["git", "push"], 300)
            return {"ticket": job.ticket.title, "id": job.ticket.id, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=False)
        history = state.history()

    by_id = {result["id"]: result for result in results}
    assert by_id["p2"]["status"] == "done", "the other ticket ran to its end"
    assert by_id["p1"]["status"] == "failed", results
    assert any("TimeoutExpired" in text for text in runner.client.comments_written), (
        runner.client.comments_written
    )
    assert [page for page, values in runner.client.written if values.get("Status") == "Failed"] == [
        "p-1"
    ], runner.client.written
    assert {entry["id"] for entry in history} == {"p1", "p2"}, "both are in the history"


@case
def a_git_command_that_hangs_is_a_failure_git_callers_already_read():
    """`subprocess.TimeoutExpired` was caught nowhere: a fetch on a remote that
    stopped answering raised through every caller up to the pass itself."""
    from ponos import git as git_module

    result = git_module.run([sys.executable, "-c", "import time; print('begun', flush=True); time.sleep(30)"], timeout=1)
    assert not result.ok and result.code == git_module.TIMED_OUT, result
    assert "timed out after 1s" in result.err, result.err


@case
def an_account_gh_did_not_know_is_asked_again_once_it_might():
    """A token found is kept; a refusal is kept for a minute and no more — the
    console lives for weeks, and a `gh auth login` typed after one failed lookup
    has to be heard without a restart."""
    from ponos import git as git_module

    answers = [git_module.Result(1, "", "not logged in"), git_module.Result(0, "gho-new", "")]
    asked: list[list[str]] = []

    def run(args, *rest, **kept):
        asked.append(args)
        return answers.pop(0)

    held = dict(git_module._TOKENS)
    git_module._TOKENS.clear()
    original_which = shutil.which
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        with _git_answering(run=run):
            assert git_module.account_token("someone") == ""
            assert git_module.account_token("someone") == "", "within the minute: not asked again"
            assert len(asked) == 1
            git_module._TOKENS["someone"] = ("", time.monotonic() - 1)  # the minute is over
            assert git_module.account_token("someone") == "gho-new"
            assert git_module.account_token("someone") == "gho-new"
            assert len(asked) == 2, "a token found is kept"
    finally:
        git_module.shutil.which = original_which
        git_module._TOKENS.clear()
        git_module._TOKENS.update(held)


@case
def a_ticket_waiting_for_credit_goes_before_one_that_never_started():
    """It is the one already half done: a branch with commits on it and a
    session that can be picked back up. Starting a fresh ticket first is how a
    board spends the returning credit on beginning things rather than on
    finishing them."""
    session_id = "11111111-2222-3333-4444-555555555555"
    # Still ready — it never went anywhere. The tick is the only difference.
    parked = _ticked(_ready("p-parked"))
    parked.properties["Session"] = {"type": "url", "url": f"ponos://session/{session_id}"}
    with _state_home(), _usage(_windows(10)):
        runner = _reserving([_ready("p-fresh"), parked])
        queued = runner.queue()[0]
        assert [ticket.id for ticket in queued] == ["pparked", "pfresh"]

        # And it is picked up rather than started over: the session on the page
        # is the one the job carries, whatever shape the column wrote it in.
        job = runner.prepare(queued[0])
        assert job.resume and job.session_id == session_id
        assert not runner.prepare(queued[1]).resume, "a fresh ticket opens a fresh session"
        # Claiming it unticks it: the wait is over the moment something starts,
        # and a tick left behind would resume a session that is running.
        claim = next(values for _, values in runner.client.written if "Waiting for credit" in values)
        assert claim["Waiting for credit"] is False


@case
def nothing_waiting_for_credit_is_ticked_twice_while_the_credit_is_still_short():
    """Re-ticking a ticket already ticked would be a Notion write per pass for
    as long as the window lasts — four hours at a ten-second cadence."""
    with _state_home(), _usage(_windows(99)):
        runner = _reserving([_ticked(_ready("p-parked"))])
        assert runner.tick() == [], "nothing is written on the way past"
        assert runner.client.written == []


@case
def what_the_reserve_says_out_loud_is_said_once_and_once_on_the_way_back():
    """A run is a process the timer starts, so "already said" has to be on disk.

    Four hours at a ten-second cadence is fourteen hundred passes; a phone that
    rings on each of them is a phone that stops being read.
    """
    with _state_home(), _usage(_windows(97)):
        runner, told = _reserving([]), []
        runner._announce = lambda title, body: told.append(title)
        for _ in range(3):
            assert runner.under_reserve() > 0.0
        assert len(told) == 1, told

    with _state_home(), _usage(_windows(97)):
        runner, told = _reserving([]), []
        runner._announce = lambda title, body: told.append(title)
        assert runner.under_reserve() > 0.0
        # The window rolls over, and the run that finds it says so — once.
        (Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".claude.json").write_text(
            json.dumps({"cachedUsageUtilization": {"utilization": _windows(4)}}),
            encoding="utf-8",
        )
        for _ in range(3):
            assert runner.under_reserve() == 0.0
        assert len(told) == 2, told


@case
def a_runner_with_no_window_to_reserve_a_slice_of_ignores_the_setting():
    """`wait_for_credits = false` says this runner is not on a metered
    subscription — an API key, or sessions routed through OpenRouter. There is
    no window there, so there is no share of one to hold back."""
    with _state_home(), _usage(_windows(99)):
        runner = _reserving([])
        runner.config.runner.wait_for_credits = False
        assert runner.under_reserve() == 0.0


@case
def a_session_picked_back_up_is_told_what_changed_and_not_the_whole_ticket():
    """It has the ticket, the brief and the context already; resending them
    would cost on every resumption what they cost once. What it cannot know is
    that hours passed and that its own half-done work is still on disk."""
    sent: list[tuple[str, bool]] = []
    page = _ticked(_reviewed("p-doc", "Ready", None))
    runner = _board_runner([page], {}, waiting=True)
    runner._live = lambda job: None
    runner.config.runner.attach_sessions = False

    def fake_run(text, **rest):
        sent.append((text, rest["resume"]))
        return session.Outcome(
            ok=True, blocked=False, session_id=rest["session_id"], summary="fait",
            log=Path("/dev/null"),
        )

    original, session.run = session.run, fake_run
    try:
        job = _doc_job(page)
        job.session_id, job.resume = "s-carried", True
        runner._run_session(job, prompt.DOCUMENT)
    finally:
        session.run = original

    text, resumed = sent[0]
    assert resumed, "`claude --resume`, not a new conversation"
    assert "carry on from where you stopped" in text
    assert page.title not in text, "the frame is not sent a second time"


@case
def a_session_that_cannot_be_picked_back_up_starts_a_fresh_one():
    """Pruned, filed on another machine, or a worktree it will not resume from.

    The ticket and its branch are still here, so the run goes on from
    everything except the thread of the interrupted session.
    """
    drawn: list[str] = []
    page = _ticked(_reviewed("p-doc", "Ready", None))
    runner = _board_runner([page], {}, waiting=True)
    runner._live = lambda job: None
    runner.config.runner.attach_sessions = False

    def fake_run(text, **rest):
        drawn.append(rest["session_id"])
        gone = rest["resume"]
        return session.Outcome(
            ok=not gone, blocked=False, session_id=rest["session_id"],
            summary="fait", error="No conversation found" if gone else "",
            log=Path("/dev/null"),
        )

    original, session.run = session.run, fake_run
    try:
        job = _doc_job(page)
        job.session_id, job.resume = "s-gone", True
        outcome = runner._run_session(job, prompt.DOCUMENT)
    finally:
        session.run = original

    assert drawn[0] == "s-gone" and drawn[1] != "s-gone", drawn
    assert outcome.ok and not job.resume


@case
def a_spent_window_mid_pass_says_so_on_the_tickets_it_did_not_start():
    """The other half of the reserve, and the older of the two roads: a session
    died on the quota while the pass was running. What it had queued behind it
    is not silently left in the ready column with nothing to explain it — it is
    ticked exactly as the ticket that died was, and comes back with it."""
    started: list[str] = []
    with _state_home(), _usage(_windows(10)):
        runner = _reserving([_ready("p-1"), _ready("p-2"), _ready("p-3")])
        runner.config.runner.max_concurrent = 1
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket, projects.Project(name="", path=None), branch="", base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            started.append(job.ticket.page.id)
            credits.hold(time.time() + 300)  # what a spent session leaves behind
            return {"id": job.ticket.page.id, "status": "waiting"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert started == ["p-1"], "the ticket in flight finished, and nothing else began"
    assert [result["status"] for result in results] == ["waiting", "waiting", "waiting"]
    assert {page for page, _ in runner.client.written} == {"p-2", "p-3"}
    assert all(values["Waiting for credit"] is True for _, values in runner.client.written)


@case
def a_reserve_is_read_off_the_file_between_none_and_half():
    """Both ends clamped rather than refused: 150 meant "keep plenty", not
    "never run again", and a negative reserve is a typo for none at all."""
    assert _config("[runner]\ncredit_reserve_percent = 10\n").runner.credit_reserve_percent == 10
    assert _config("[runner]\ncredit_reserve_percent = 150\n").runner.credit_reserve_percent == 50
    assert _config("[runner]\ncredit_reserve_percent = -3\n").runner.credit_reserve_percent == 0
    assert _config("[runner]\n").runner.credit_reserve_percent == 5


# -- runner ------------------------------------------------------------------


@case
def a_template_only_body_counts_as_blank():
    """A Notion template fills a new page with empty headings.

    They are not blank text, so without this they would travel into the prompt
    as noise and stop the "everything is in the title" fallback from firing.
    """
    from ponos.ticket import is_blank

    assert is_blank("## Ce qu'il faut faire\n## Où\n## Comment on saura\n")
    assert is_blank("")
    assert is_blank("   \n\n---\n")
    assert not is_blank("## Ce qu'il faut faire\nRetirer le header.")
    assert not is_blank("Une seule ligne de texte")


# -- a merged pull request closes its ticket ---------------------------------


class _BoardClient:
    """A tickets database that answers queries and remembers what was written."""

    def __init__(
        self, pages: list[notion.Page], options: list[str] | None = None, waiting: bool = False
    ):
        self._pages = pages
        self._options = options if options is not None else ["In review", "Validated", "Done"]
        # A board that predates the attribute simply has no such property, and
        # the runner then waits for the credit with nothing to show for it.
        self.waiting = waiting
        self.written: list[tuple[str, dict]] = []
        self.comments_written: list[str] = []
        self.queried: list[object] = []
        self.created: list[tuple[str, dict]] = []
        self.bodies: list[str] = []
        # Columns a test adds to the board: the Runner one, to begin with.
        self.columns: dict[str, str] = {}

    def schema(self, database_id: str) -> dict[str, str]:
        schema = {"Status": "status", "Pull Request": "url", **self.columns}
        if self.waiting:
            schema["Waiting for credit"] = "checkbox"
        return schema

    def options(self, database_id: str, name: str) -> list[str]:
        return list(self._options)

    def me(self) -> str:
        return "u-runner"

    def comments(self, page_id: str) -> list[notion.Comment]:
        return []

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return "Le post d'annonce, écrit la semaine dernière et relu depuis."

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        self.queried.append(filter_)
        wanted = (filter_ or {}).get("status", {}).get("equals")
        return [page for page in self._pages if notion.read(page, "Status") == wanted]

    def page(self, page_id: str) -> notion.Page:
        # The very page the pass read: what a run holds is what Notion says,
        # unless a test moves it underneath.
        for page in self._pages:
            if page.id.replace("-", "") == page_id.replace("-", ""):
                return page
        raise notion.NotionError(f"GET /pages/{page_id}: 404 not found")

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        self.written.append((page_id, values))

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.comments_written.append(text)

    def create_row(self, database_id: str, title: str, values: dict | None = None) -> str:
        page_id = f"created{len(self.created)}"
        self.created.append((title, values or {}))
        status = (values or {}).get("Status", "")
        self._pages.append(
            notion.Page(
                id=page_id, url="", title=title,
                properties={"Status": {"type": "status", "status": {"name": status}}},
            )
        )
        return page_id

    def append_markdown(self, page_id: str, text: str) -> None:
        self.bodies.append(text)


def _ticked(page: notion.Page) -> notion.Page:
    """The same page, ticked as waiting for credit — where a pass left it."""
    page.properties["Waiting for credit"] = {"type": "checkbox", "checkbox": True}
    return page


def _reviewed(page_id: str, status: str, pull_request: str | None) -> notion.Page:
    properties = {"Status": {"type": "status", "status": {"name": status}}}
    if pull_request is not None:
        properties["Pull Request"] = {"type": "url", "url": pull_request}
    return notion.Page(id=page_id, url="", title=page_id, properties=properties)


def _board_runner(
    pages: list[notion.Page], status: dict[str, str], options=None, waiting: bool = False
) -> Runner:
    """A Runner with nothing underneath it but a fake board."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = _BoardClient(pages, options, waiting)
    runner.config = C.Config(
        notion=C.Notion(properties=dict(C._DEFAULT_PROPERTIES), status=status),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner.dry_run = False
    runner._claimed = set()
    runner._holding, runner._explained = {}, None
    runner._comments = {}
    runner._usage_warned = False
    runner._spellings = conversation.names()
    runner._me = ""
    runner._identity_error = ""
    runner._ledger_lock = threading.Lock()
    runner._landed, runner._replayed_after = {}, {}
    runner._landed_lock = threading.Lock()
    runner._queues = {}
    runner._ledger = conversation.Ledger(
        database=Path(tempfile.mkdtemp()) / "ponos.db"
    )
    return runner


@contextmanager
def _github(states: dict[str, str], merge=None, blockers: dict[str, str] | None = None):
    """`gh`, replaced by what it would have said.

    `blockers` is what GitHub says stands in a pull request's way before a merge
    is asked — see `git.merge_blocker`. Nothing, unless a test says otherwise.
    """
    from ponos import git as git_module

    asked, original = git_module.pull_request_state, git_module.merge_pull_request
    blocker = git_module.merge_blocker
    git_module.pull_request_state = lambda url, accounts=None: states.get(url, "")
    git_module.merge_blocker = lambda url, accounts=None: (blockers or {}).get(url, "")
    # Nothing is asked of GitHub about the checks of the pull requests still open.
    head = git_module.pull_request_head
    git_module.pull_request_head = lambda url, accounts=None: ""
    if merge is not None:
        git_module.merge_pull_request = merge
    try:
        yield
    finally:
        git_module.pull_request_state = asked
        git_module.merge_pull_request = original
        git_module.merge_blocker = blocker
        git_module.pull_request_head = head


def _closing(pages: list[notion.Page], states: dict[str, str], status: dict[str, str]):
    """Run `close_merged` against a fake board and a fake GitHub."""
    runner = _board_runner(pages, status)
    with _github(states):
        return runner.client, runner.close_merged()


@case
def a_merged_pull_request_moves_its_ticket_to_done():
    client, closed = _closing(
        [
            _reviewed("p-merged", "In review", "https://github.com/x/y/pull/1"),
            _reviewed("p-open", "In review", "https://github.com/x/y/pull/2"),
            _reviewed("p-ready", "Not started", None),
        ],
        {"https://github.com/x/y/pull/1": "MERGED", "https://github.com/x/y/pull/2": "OPEN"},
        {"review": "In review", "done": "Done"},
    )
    assert closed == 1
    assert client.written == [("p-merged", {"Status": "Done"})]
    assert client.comments_written[0] == (
        "✅ Merged — PR #1\nhttps://github.com/x/y/pull/1"
    )


def _checks(*buckets: str) -> list[dict]:
    return [
        {"name": f"job-{number}", "bucket": bucket, "link": f"https://ci/{number}"}
        for number, bucket in enumerate(buckets)
    ]


@case
def the_three_states_of_the_ci_are_deduced_from_the_checks():
    from ponos import ci

    assert ci.deduce(_checks("pass", "pass")) == "passed"
    assert ci.deduce(_checks("pass", "skipping")) == "passed"
    assert ci.deduce(_checks("pass", "pending")) == "pending"
    assert ci.deduce(_checks("fail", "pass")) == "failed"
    assert ci.deduce(_checks("cancel", "pass")) == "failed"
    # The verdict is known as soon as one is red, whatever is still running.
    assert ci.deduce(_checks("pending", "fail")) == "failed"
    # No check is no CI: never a green.
    assert ci.deduce([]) == ""
    assert ci.read({"state": "", "url": "u", "checks": []}, "u") is None


@case
def a_push_puts_the_ci_back_to_running_until_the_new_checks_are_in():
    from ponos import ci

    url = "https://github.com/x/y/pull/1"
    green = ci.settle(None, url, "aaa", _checks("pass"), 1000.0)
    assert green["state"] == "passed" and green["head"] == "aaa"
    # Same commit, same checks: nothing moves, and the date of the head stays.
    again = ci.settle(green, url, "aaa", _checks("pass"), 1400.0)
    assert again["state"] == "passed" and again["since"] == 1000.0
    # A new head whose checks are not registered yet is still running.
    pushed = ci.settle(again, url, "bbb", [], 1500.0)
    assert pushed["state"] == "pending" and pushed["since"] == 1500.0
    # A repository that never had a check says nothing, at the first reading and after.
    assert ci.settle(None, url, "aaa", [], 1000.0)["state"] == ""
    # And a pull request that answers with nothing for good is not kept pending.
    assert ci.settle(pushed, url, "bbb", [], 1500.0 + ci.APPEAR_SECONDS)["state"] == ""


@case
def the_ci_is_asked_again_often_while_it_runs_and_rarely_once_it_has_settled():
    from ponos import ci

    url = "u"
    running = {"url": url, "state": "pending", "asked": 1000.0}
    settled = {"url": url, "state": "passed", "asked": 1000.0}
    assert ci.due(None, url, 1000.0) and ci.due({**running, "url": "other"}, url, 1000.0)
    assert not ci.due(running, url, 1000.0 + ci.RUNNING_SECONDS - 1)
    assert ci.due(running, url, 1000.0 + ci.RUNNING_SECONDS)
    assert not ci.due(settled, url, 1000.0 + ci.RUNNING_SECONDS)
    assert ci.due(settled, url, 1000.0 + ci.SETTLED_SECONDS)


@case
def a_ticket_in_review_carries_its_ci_on_the_board_and_stops_when_it_leaves():
    from ponos import git as git_module

    url = "https://github.com/x/y/pull/2"
    with _state_home():
        runner = _board_runner(
            [_reviewed("p-open", "In review", url)], {"review": "In review", "done": "Done"}
        )
        asked = []
        head, listed = git_module.pull_request_head, git_module.checks
        git_module.pull_request_head = lambda link, accounts=None: "aaa"
        git_module.checks = lambda link, accounts=None: asked.append(link) or _checks("pass", "pending")
        try:
            with _github({url: "OPEN"}):
                git_module.pull_request_head = lambda link, accounts=None: "aaa"
                runner.close_merged()
            # Written to the board, and kept for the list to read without GitHub.
            assert runner.client.written == [("p-open", {"CI": "en cours"})], runner.client.written
            cards = [{"id": "popen", "column": "review", "pull_request": url}]
            web_api._checks(cards)
            assert cards[0]["ci"]["state"] == "pending" and len(cards[0]["ci"]["checks"]) == 2
            assert cards[0]["ci"]["link"] == url + "/checks"
            # Asked again at once: not due, so GitHub is not.
            with _github({url: "OPEN"}):
                git_module.pull_request_head = lambda link, accounts=None: "aaa"
                runner.close_merged()
            assert asked == [url]
            # Out of review: no longer followed, no longer drawn.
            runner.client.written.clear()
            runner.follow_ci([])
            assert state.ci_rows() == {}
            cards = [{"id": "popen", "column": "validated", "pull_request": url}]
            web_api._checks(cards)
            assert cards[0]["ci"] is None
        finally:
            git_module.pull_request_head, git_module.checks = head, listed


@case
def a_board_told_to_answer_in_french_is_answered_in_french():
    """The whole point of the setting, checked where it is actually read.

    `runner.language` is a line of a file; what it has to change is the sentence
    written under a ticket, and nothing in between is worth checking on its own.
    """
    runner = _board_runner(
        [_reviewed("p-merged", "In review", "https://github.com/x/y/pull/1")],
        {"review": "In review", "done": "Done"},
    )
    runner.config.runner.language = "FR"
    with _github({"https://github.com/x/y/pull/1": "MERGED"}):
        assert runner.close_merged() == 1
    said = runner.client.comments_written[0]
    assert said.startswith("✅ Fusionnée — PR #1"), said
    assert "https://github.com/x/y/pull/1" in said


@case
def a_stuck_ticket_in_french_is_stuck_in_french_from_the_first_line_to_the_phone():
    """The comment that asked for the setting: a French question wrapped in
    three English sentences. Every line of it comes out of `voice`, and so does
    the message that reaches the phone."""
    runner = _board_runner([_reviewed("p-stuck", "In progress", None)], {"blocked": "Blocked"})
    runner.config.runner.language = "fr"
    runner.config.notify = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    ).notify
    said = runner.voice
    ticket = ticket_module.Ticket(runner.client._pages[0])
    sent: list[str] = []
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
    try:
        runner._fail(
            ticket,
            said.say("asked-something"),
            code="session.question",
            blocked=True,
            question="Audit déjà livré et validé : on le refait ?",
            note=said.say("trace-in-page"),
        )
    finally:
        channels.announce = original
    comment = runner.client.comments_written[0]
    assert comment == "🙋 Bloqué\nAudit déjà livré et validé : on le refait ?", comment
    assert sent and sent[0].startswith("🙋 Bloqué · p-stuck"), sent
    english = voice.Voice("en")
    for key in ("verdict-blocked", "yes-or-no", "trace-in-page"):
        assert english.say(key) not in comment + sent[0], key
    # The folded block and the session's footer, said the same way.
    assert said.count(130, "step") + " · " + said.minutes(19 * 60) == "130 étapes · 19 minutes"
    assert said.minutes(20.0) == "moins d'une minute"
    assert said.trace("claude --resume abc", "/tmp/log").startswith("Pour reprendre la session")


# -- the question a blocked ticket asks ---------------------------------------

# What the session of the 02/10 ticket would hand over: PR #58 verified and
# ready, the merge forbidden in its session. The comment it got was one block —
# what was done, the technical detail and the footer — and no question at all.
PR_58 = (
    "J'ai vérifié la PR : build vert, vidéo de 56 s, QR code lisible.\n\n"
    "DONE: [PR #58](https://github.com/salva/site/pull/58) prête (build ok)\n"
    "WHY: Je n'ai pas le droit de fusionner sur main.\n"
    "QUESTION: Qui fusionne la PR #58 ?\n"
    "MODE: choice\n"
    "OPTION: Tu fusionnes toi-même\n"
    "OPTION: Tu m'autorises à fusionner\n"
    "OPTION: On attend\n\n"
    "RESULT: blocked — PR #58 prête, la fusion sur main est interdite dans cette session"
)


def _asking(question: object, language: str = "fr") -> tuple[Runner, str, list[str]]:
    """A ticket blocked on `question`: the comment written, and what reached the phone."""
    runner = _board_runner([_reviewed("p-stuck", "In progress", None)], {"blocked": "Blocked"})
    runner.config.runner.language = language
    runner.config.notify = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    ).notify
    sent: list[str] = []
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
    try:
        runner._fail(
            ticket_module.Ticket(runner.client._pages[0]),
            runner.voice.say("asked-something"),
            "la session a résumé ça autrement",
            code="session.question",
            blocked=True,
            question=question,
            note=runner.voice.say("trace-in-page"),
        )
    finally:
        channels.announce = original
    return runner, runner.client.comments_written[0], sent


@case
def a_yes_no_question_says_the_two_words_that_answer_it():
    from ponos import question
    asked = question.Question(
        ask="Je fusionne et je déploie ?",
        mode="yes-no",
        done="PR #58 prête (build ok)",
        why="Je n'ai pas le droit de fusionner sur main.",
    )
    _, comment, sent = _asking(asked)
    assert comment.split("\n") == [
        "🙋 Bloqué — PR #58 prête (build ok)",
        "Je n'ai pas le droit de fusionner sur main.",
        "Je fusionne et je déploie ? → oui / non",
    ], comment
    assert "Une réponse ici" not in comment and "bloc replié" not in comment, "no footer"
    assert "la session a résumé" not in comment, "the session's own question says it all"
    assert sent[0].split("\n")[1:4] == [
        "PR #58 prête (build ok)",
        "Je n'ai pas le droit de fusionner sur main.",
        "Je fusionne et je déploie ? → oui / non",
    ], "the phone gets the same lines"
    _, english, _ = _asking(asked, "en")
    assert english.endswith("Je fusionne et je déploie ? → yes / no"), english


@case
def a_choice_is_numbered_on_one_line_so_that_a_number_answers_it():
    from ponos import question
    _, comment, _ = _asking(
        question.Question(
            ask="Qui fusionne ?",
            mode="choice",
            options=["Tu fusionnes toi-même", "Tu m'autorises à fusionner", "On attend"],
            why="Je n'ai pas le droit de fusionner sur main.",
        )
    )
    assert comment.split("\n") == [
        "🙋 Bloqué",
        "Je n'ai pas le droit de fusionner sur main.",
        "Qui fusionne ?",
        "1. Tu fusionnes toi-même · 2. Tu m'autorises à fusionner · 3. On attend",
    ], comment
    # A choice of one is no choice, and five is a menu.
    assert question.Question(ask="?", mode="choice", options=["seule"]).mode == "free"
    assert len(question.Question(ask="?", mode="choice", options=list("abcde")).options) == 4


@case
def a_free_question_stands_alone_and_says_what_to_give():
    from ponos import question
    _, comment, _ = _asking(question.Question(ask="Quelle URL pour le site de Wizaplace ?"))
    assert comment == "🙋 Bloqué\nQuelle URL pour le site de Wizaplace ?", comment
    # A question the runner asks on its own behalf is a free one, and its
    # detail still goes under it — after a blank line, out of the question.
    _, plain, _ = _asking("Quel en-tête ?")
    assert plain == "🙋 Bloqué\nQuel en-tête ?\n\nla session a résumé ça autrement", plain


@case
def a_blocked_comment_reaches_notion_with_real_line_breaks_and_a_link():
    from ponos import question
    _, comment, _ = _asking(question.parse(PR_58))
    pieces = notion._comment_text(comment)
    drawn = "".join(piece["text"]["content"] for piece in pieces)
    assert drawn.count("\n") == 3, "four lines, three breaks, none of them flattened"
    assert "\\n" not in drawn, "a break, not its escape"
    linked = [piece for piece in pieces if piece["text"].get("link")]
    assert linked == [
        {"type": "text", "text": {"content": "PR #58", "link": {"url": "https://github.com/salva/site/pull/58"}}}
    ], linked
    # And read back as it was written, so the console and the next run see the link.
    read = "".join(notion._written({"plain_text": piece["text"]["content"], **piece}) for piece in pieces)
    assert read == comment
    assert notion._comment_text("[x](javascript:alert(1))")[0]["text"].get("link") is None


@case
def the_pull_request_58_comes_back_as_a_clear_choice_in_four_lines():
    """The 02/10 comment, played again: a choice, and nothing else."""
    from ponos import question
    asked = question.parse(PR_58)
    assert asked and asked.mode == "choice", asked
    _, comment, _ = _asking(asked)
    assert comment.split("\n") == [
        "🙋 Bloqué — [PR #58](https://github.com/salva/site/pull/58) prête (build ok)",
        "Je n'ai pas le droit de fusionner sur main.",
        "Qui fusionne la PR #58 ?",
        "1. Tu fusionnes toi-même · 2. Tu m'autorises à fusionner · 3. On attend",
    ], comment
    assert "56 s" not in comment and "QR" not in comment, "the detail stays in the folded block"
    # What was written is what is read back when the answer arrives.
    again = question.found(comment)
    assert (again.mode, again.ask, again.options) == ("choice", asked.ask, asked.options)


@case
def a_session_that_wrote_no_question_blocks_the_way_it_always_did():
    from ponos import question
    assert question.parse("RESULT: blocked — quel en-tête ?") is None
    found = question.parse("**QUESTION:** On publie ?\n- MODE: yes/no\nRESULT: blocked — x")
    assert found and (found.ask, found.mode) == ("On publie ?", "yes-no"), found
    assert question.found("🙋 Bloqué — Quel en-tête ?") is None, "an older report: no question to read"
    assert question.found("✅ À relire — PR #1\nFait.") is None


@case
def an_answer_is_read_as_the_option_it_names_whatever_its_shape():
    from ponos import question
    choice = question.Question(
        ask="Qui fusionne ?",
        mode="choice",
        options=["Tu fusionnes toi-même", "Tu m'autorises à fusionner", "On attend"],
    )
    for text, option in (
        ("2", 2), ("la 2", 2), ("2.", 2), ("#3", 3), ("option 1", 1), ("la deuxième", 2),
        ("2, mais sans déployer", 2), ("on attend", 3), ("Option 2 : Tu m'autorises à fusionner.", 2),
    ):
        reading = question.read(text, choice)
        assert (reading.kind, reading.option) == ("option", option), (text, reading)
    assert question.read("2", choice).label == "Tu m'autorises à fusionner"
    assert question.read("5", choice).kind == "free", "an option nobody offered"
    assert question.read("un détail : attends lundi", choice).kind == "free"
    yes_no = question.Question(ask="Je fusionne ?", mode="yes-no")
    for text, kind in (("oui", "yes"), ("ok", "yes"), ("Non", "no"), ("2", "free")):
        assert question.read(text, yes_no).kind == kind, text
    free = question.read("https://wizaplace.example", question.Question(ask="Quelle URL ?"))
    assert (free.kind, free.text) == ("free", "https://wizaplace.example")


@case
def an_answer_from_a_phone_is_written_as_the_option_it_chose():
    from ponos import question
    _, comment, _ = _asking(question.parse(PR_58))
    said = voice.Voice("fr")
    asked = question.waiting([comment])
    reply = channels.Reply(channel="telegram", text="2", who="Salva", ticket=TICKET)
    assert channels.answer(reply, said, asked) == (
        "Répondu depuis Telegram par Salva.\nOption 2 : Tu m'autorises à fusionner."
    )
    reply.text = "la 2, mais sans déployer"
    assert channels.answer(reply, said, asked).splitlines()[1:] == [
        "Option 2 : Tu m'autorises à fusionner.", "la 2, mais sans déployer",
    ]
    reply.text = "oui"
    assert channels.answer(reply, said, asked).splitlines()[1:] == ["oui"], (
        "a yes to a list of roads takes none of them"
    )
    # The question a page waits on is its last report's, and only if that one asked.
    assert question.waiting([comment, "2", "✅ À relire — PR #58\nFait."]) is None
    # Through the runner: the question is read off the ticket's own comments.
    runner, _ = _answering(
        [channels.Reply(channel="telegram", text="3", ticket=TICKET, title="Le site")],
        asked=[comment],
    )
    assert runner.client.written[0][1].endswith("Option 3: On attend."), runner.client.written


@case
def the_next_run_is_told_the_question_and_what_the_answer_chose():
    from ponos import question
    _, comment, _ = _asking(question.parse(PR_58))
    _, lines = _runner_reading([comment, "la 2"])
    assert lines == [
        "a previous run: 🙋 Bloqué — [PR #58](https://github.com/salva/site/pull/58) prête "
        "(build ok) Je n'ai pas le droit de fusionner sur main. — asked: Qui fusionne la PR #58 ? "
        "(options: 1. Tu fusionnes toi-même; 2. Tu m'autorises à fusionner; 3. On attend)",
        "the ticket's author: la 2 (read as: option 2, “Tu m'autorises à fusionner”)",
    ], lines
    _, plain = _runner_reading(["🙋 Stuck\nWhich header? → yes / no", "yes"])
    assert plain[-1] == "the ticket's author: yes (read as: yes)", plain


@case
def every_session_that_can_block_is_told_how_to_ask():
    common = dict(project="p", title="t", body="b", repo="/r", branch="br", base="main", url="u")
    for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.DELIVERY, prompt.RESOLVE):
        text = prompt.build(template, **common)
        assert "QUESTION: <" in text and "MODE: <yes-no, choice or free>" in text, template[:40]
    assert "{asking}" not in prompt.build("{title}", **common), "a prompt of your own is left alone"


@case
def an_answer_is_understood_in_either_language_and_relayed_in_the_runners():
    """« oui » on a board told to speak English, `yes` on one told French: the
    word is read whatever it was typed in, and spelled out in the runner's."""
    for text, verdict in (("oui", "yes"), ("yes", "yes"), ("non", "no"), ("no", "no")):
        assert channels.decide(text) == verdict, text
    reply = channels.Reply(channel="telegram", text="yes", who="Salva", ticket=TICKET)
    relayed = channels.answer(reply, voice.Voice("fr"))
    assert relayed == "Répondu depuis Telegram par Salva.\nOui — vas-y avec ce que tu as proposé."
    assert conversation.is_relayed(relayed), "and it still wakes the ticket"
    assert channels.answer(reply) == "Answered from Telegram by Salva.\nYes — go ahead with what you proposed."
    assert conversation.is_relayed("Answered from Slack.\nok"), "a board keeps the old ones"
    assert conversation.said(relayed) == "Oui — vas-y avec ce que tu as proposé."


@case
def what_the_runner_writes_on_github_and_on_a_schedules_ticket_follows_the_language():
    said = voice.Voice("fr")
    body = said.pull_request_body("Le header est parti.", "https://notion.so/t", "abc", 3)
    assert body == (
        "Le header est parti.\n\n---\nTicket Notion : https://notion.so/t\n"
        "Session Claude Code : `abc`\nOuverte par ponos (3 commits)."
    ), body
    assert voice.Voice().pull_request_body("s", "u", "abc", 1).endswith(
        "Opened by ponos (1 commit)."
    ), "and English says what it always said"
    assert said.say("born-of-schedule", name="Veille", stamp="2026-10-02", url="u") == (
        "*Né de la récurrence « Veille », 2026-10-02* — u"
    )
    assert "Ponos" in said.say("out-of-credit") and said.say("out-of-credit") != voice.Voice().say(
        "out-of-credit"
    )


@case
def the_console_opens_in_the_language_the_file_names_and_follows_the_reports_by_default():
    """One line — `language = "fr"` — is enough to have everything in French;
    `app_language` is for whoever wants the two apart."""
    from ponos.web import server as web_server

    settings = C.Runner()
    assert settings.interface_language() == "", "nothing said: the browser decides"
    settings.language = "fr"
    assert settings.interface_language() == "fr", "the console follows the reports"
    settings.app_language = "en"
    assert settings.interface_language() == "en", "unless it is told otherwise"
    loaded = _config('[runner]\nlanguage = "fr"\napp_language = "en"\n').runner
    assert (loaded.language, loaded.app_language) == ("fr", "en")

    page = b'<!doctype html>\n<html lang="en" class="dark">\n<body></body></html>'
    assert web_server.configured(page, "") == page, "nothing said, nothing written"
    marked = web_server.configured(page, "fr")
    assert marked.startswith(b'<!doctype html>\n<html data-language="fr" lang="en" class="dark">')
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    assert b"\napp_language = " in example.read_bytes(), "documented where every key is"
    fields = {(field.table, field.key) for section in web_settings.SECTIONS for field in section.fields}
    assert ("runner", "app_language") in fields, "and the Settings screen offers it"


@case
def a_ticket_is_never_closed_on_an_answer_github_did_not_give():
    """No pull request, or no `gh` to ask: the ticket stays where it is."""
    client, closed = _closing(
        [
            _reviewed("p-nothing", "In review", None),
            _reviewed("p-empty", "In review", ""),
            _reviewed("p-unreachable", "In review", "https://github.com/x/y/pull/3"),
        ],
        {},  # as when gh is missing or not authenticated
        {"review": "In review", "done": "Done"},
    )
    assert closed == 0 and client.written == []


@case
def the_columns_are_read_in_one_order_with_blocked_right_after_running():
    """The console, its filters and the MCP tools share one order, cancelled last."""
    from ponos.web import api, mcp

    order = api.COLUMNS
    assert order.index("blocked") == order.index("running") + 1, order
    assert order[-2:] == ("done", "cancelled"), order
    assert [key for key in order if key not in ("blocked",)] == [
        "ready", "running", "review", "validated", "failed", "done", "cancelled"
    ], order
    assert mcp.STATUSES == ("draft", *order), mcp.STATUSES


@case
def a_board_without_a_review_column_is_never_even_queried():
    """`review` following `done` means there is nowhere for a ticket to wait."""
    client, closed = _closing(
        [_reviewed("p-done", "Done", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {"done": "Done"},
    )
    assert closed == 0 and client.written == []



# -- validating is the gesture the runner acts on ----------------------------


def _validating(
    pages: list[notion.Page],
    states: dict[str, str],
    status: dict[str, str],
    *,
    options=None,
    refuses: str = "",
):
    """Run `deliver` against a fake board, a fake GitHub, and no session."""
    from ponos import git as git_module

    runner = _board_runner(pages, status, options)
    merges: list[tuple[str, str]] = []
    published: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        merges.append((url, method))
        if refuses:
            raise git_module.GitError(refuses)
        return "merged"

    # Publishing runs a Claude session, which is the one thing these tests do
    # not do: what is checked here is that a ticket with no pull request goes
    # down that road at all.
    runner._publish = lambda ticket, project: published.append(ticket.id)
    with _github(states, merge=merge):
        return runner.client, merges, published, runner.deliver()


@case
def validating_a_ticket_is_what_merges_its_pull_request():
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
    )
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert client.written == [("p-validated", {"Status": "Done"})]
    assert results and results[0]["status"] == "done"
    assert client.comments_written[0].startswith("✅ Merged — PR #1 · squash merge")


@case
def a_pull_request_already_merged_only_moves_its_ticket():
    """Merged by hand between two runs: nothing to merge, still done."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"Status": "Done"})]
    assert client.comments_written[0].startswith("✅ Merged — PR #1 · already merged")


@case
def a_merge_github_refuses_leaves_the_ticket_blocked_and_says_why():
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        refuses="gh pr merge: Pull request is not mergeable: the merge commit cannot be cleanly created",
    )
    assert len(merges) == 1, "refused once, not retried in the same pass"
    assert client.written == [("p-validated", {"Status": "Blocked", "Blocage": "merge.refused"})]
    assert "not mergeable" in client.comments_written[0]
    assert results and results[0]["status"] == "blocked"


@case
def a_pull_request_closed_rather_than_merged_is_a_question_not_a_merge():
    client, merges, _, _ = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "CLOSED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"Status": "Blocked", "Blocage": "merge.pr-closed"})]


@case
def nothing_is_merged_on_an_answer_github_did_not_give():
    """`gh` missing or unauthenticated: the ticket waits for the next pass."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {},
        {},
    )
    assert merges == [] and client.written == [] and results == []


@case
def a_validated_ticket_with_no_pull_request_is_published_rather_than_merged():
    """The Instagram post, the email, the announcement: work with no branch."""
    client, merges, published, _ = _validating(
        [
            _reviewed("p-post", "Validated", None),
            _reviewed("p-empty", "Validated", ""),
        ],
        {},
        {},
    )
    assert merges == [] and client.written == []
    assert published == ["ppost", "pempty"]  # `Ticket.id` drops the dashes


@case
def a_board_without_a_validated_column_is_never_even_queried():
    """No such option on the board, no such gesture: not even a query."""
    client, merges, published, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        options=["Ready", "In progress", "In review", "Done"],
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == [], "a board with no column is not read at all"


@case
def a_file_that_names_its_columns_without_validated_asked_for_no_gesture():
    """Most often a file written before the column existed. It stays as it was."""
    settings = C.Notion(status={"review": "In review", "done": "Done"})
    assert settings.state("validated") == settings.state("review") == "In review"

    # But renaming some other column says nothing about this one: a file that
    # only translates "Ready" has not asked for the gesture to go away.
    settings = C.Notion(status={"ready": "À faire"})
    assert settings.state("validated") == "Validated"
    assert settings.state("ready") == "À faire"

    client, merges, published, results = _validating(
        [_reviewed("p-review", "In review", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {"review": "In review", "done": "Done"},
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == []

    # And a file that names nothing at all gets the whole board, gesture included.
    assert C.Notion().state("validated") == "Validated"


@case
def a_validated_ticket_on_a_repository_with_no_pull_request_asks_rather_than_publishes():
    """Nothing to merge, and nothing on the page to publish: a question."""
    runner = _board_runner([_reviewed("p-code", "Validated", None)], {})
    runner.resolver = None
    runner._project_of = lambda ticket: projects.Project(name="Site", path=Path("/repo"))
    results = runner.deliver()
    assert runner.client.written == [("p-code", {"Status": "Blocked", "Blocage": "merge.no-pr"})]
    assert runner.client.comments_written[0].startswith(
        "🙋 Stuck\nThis ticket was validated but carries no pull request."
    )
    assert results and results[0]["status"] == "blocked"


@case
def a_dry_run_says_what_it_would_merge_and_merges_nothing():
    runner = _board_runner(
        [
            _reviewed("p-pr", "Validated", "https://github.com/x/y/pull/1"),
            _reviewed("p-post", "Validated", None),
        ],
        {},
    )
    runner.dry_run = True
    said: list[str] = []
    runner.quiet = False
    runner.say = said.append
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        results = runner.deliver()
    assert runner.client.written == [], "a dry run writes nothing"
    assert [done["status"] for done in results] == ["dry-run", "dry-run"]
    assert any("would merge https://github.com/x/y/pull/1" in line for line in said)
    assert any("would publish what it holds" in line for line in said)


def _never_merged(url: str, method: str = "squash") -> str:
    raise AssertionError("a dry run never merges anything")


def _dated(page: notion.Page, when: str) -> notion.Page:
    """The same ticket, with a date on it."""
    page.properties["Scheduled"] = {"type": "date", "date": {"start": when}}
    return page


def _in(**delta) -> str:
    """A Notion date this far from now, as the board would store it."""
    from datetime import datetime, timedelta

    return (datetime.now().astimezone() + timedelta(**delta)).isoformat(timespec="minutes")


@case
def a_validated_publication_waits_for_its_date():
    """The post is written and accepted; the hour it goes out is still the one
    the ticket names."""
    runner = _board_runner([_dated(_reviewed("ppost", "Validated", None), _in(days=2))], {})
    runner._publish = lambda ticket, project: (_ for _ in ()).throw(
        AssertionError("published before its date")
    )
    assert runner.deliver() == []
    assert runner.client.written == [], "nothing is claimed, nothing moves"
    held = runner._deferred
    assert [ticket.id for ticket, _ in held] == ["ppost"]
    assert "ppost" in runner._claimed, "its comments go into the publication, not an answer"


@case
def a_validated_pull_request_waits_for_its_date_too():
    """One column, one rule: a merge is held back like a publication."""
    runner = _board_runner(
        [_dated(_reviewed("ppr", "Validated", "https://github.com/x/y/pull/1"), _in(hours=3))],
        {},
    )
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        assert runner.deliver() == []
    assert runner.client.written == []
    assert [ticket.id for ticket, _ in runner._deferred] == ["ppr"]
    assert "ppr" not in runner._claimed, "a ticket with a pull request stays talkable-to"


@case
def a_validated_ticket_whose_date_has_passed_is_carried_out_at_once():
    """The date says "not before", never "not until somebody looks again"."""
    runner = _board_runner(
        [_dated(_reviewed("ppr", "Validated", "https://github.com/x/y/pull/1"), _in(hours=-1))],
        {},
    )
    merges: list[tuple[str, str]] = []
    with _github(
        {"https://github.com/x/y/pull/1": "OPEN"},
        merge=lambda url, method="squash", accounts=None: (
            merges.append((url, method)) or "merged"
        ),
    ):
        results = runner.deliver()
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert results and results[0]["status"] == "done"
    assert runner._deferred == []


@case
def a_validated_date_that_cannot_be_read_never_holds_a_publication_back():
    """The same rule as the queue: an unreadable date freezes nothing."""
    runner = _board_runner([_dated(_reviewed("ppost", "Validated", None), "bientôt")], {})
    published: list[str] = []
    runner._publish = lambda ticket, project: published.append(ticket.id)
    runner._project_of = lambda ticket: projects.Project(name="Blog", path=None)
    runner.deliver()
    assert published == ["ppost"] and runner._deferred == []


@case
def what_the_validated_column_is_holding_back_is_listed():
    """`ponos list` shows the whole calendar, both columns of it."""
    runner = _board_runner(
        [
            _dated(_reviewed("plater", "Validated", None), _in(days=3)),
            _dated(_reviewed("psoon", "Validated", None), _in(hours=2)),
            _reviewed("pnow", "Validated", None),
            _dated(_reviewed("pelsewhere", "Ready", None), _in(hours=1)),
        ],
        {},
    )
    assert [ticket.id for ticket, _ in runner.scheduled()] == ["psoon", "plater"]


@case
def a_publication_a_crash_interrupted_comes_back_as_a_question():
    """Put back in ready it would be redone; the post may already be out."""
    claimed = notion.Page(
        id="ppost",  # `Ticket.id` drops the dashes, and a claim is filed under it
        url="",
        title="Le post",
        properties={
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Runner": {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    with _state_home():
        state.claim("ppost", "Validated")
        recovered = runner.sweep()
        assert state.claims() == {}, "the note is dropped once it has been read"
    assert recovered == 1
    assert runner.client.written == [("ppost", {"Status": "Blocked", "Blocage": "worktree.interrupted"})]
    said = runner.client.comments_written[0]
    assert said.startswith("🙋 Stuck\nIts publication was interrupted")
    assert "“Validated”" in said and "An answer here" not in said


@case
def a_ticket_claimed_from_ready_is_still_put_back_in_the_queue():
    claimed = notion.Page(
        id="p-work",
        url="",
        title="Le header",
        properties={
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Runner": {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    with _state_home():
        assert runner.sweep() == 1
    assert runner.client.written == [("p-work", {"Status": "Ready"})]
    assert "picking it up again" in runner.client.comments_written[0]


def _in_progress(page_id: str, runner_label: str | None) -> notion.Page:
    """A ticket left in progress long ago, signed by `runner_label` if given."""
    properties: dict = {"Status": {"type": "status", "status": {"name": "In progress"}}}
    if runner_label is not None:
        properties["Runner"] = {"type": "rich_text", "rich_text": [{"plain_text": runner_label}]}
    return notion.Page(
        id=page_id, url="", title=page_id, properties=properties,
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )


@case
def a_board_without_a_runner_column_still_gets_its_abandoned_tickets_back():
    """The 1st of October: fourteen tickets in progress, nobody behind them.

    The claims were never signed — the board had no such column — and the
    sweep only put back what this host had signed.
    """
    runner = _board_runner([_in_progress("p-lost", None), _in_progress("p-other", None)], {})
    with _state_home():
        assert runner.sweep() == 2
    assert runner.client.written == [("p-lost", {"Status": "Ready"}), ("p-other", {"Status": "Ready"})]


@case
def the_machines_free_memory_is_read_from_meminfo_and_a_guard_under_the_threshold_says_so():
    from ponos import resources

    with tempfile.TemporaryDirectory() as directory:
        meminfo = Path(directory) / "meminfo"
        meminfo.write_text("MemTotal: 16000000 kB\nMemFree: 100 kB\nMemAvailable: 1048576 kB\n")
        assert resources.available_mb(str(meminfo)) == 1024
        assert resources.available_mb(str(Path(directory) / "nothing")) is None
        meminfo.write_text("MemTotal: 16000000 kB\n")
        assert resources.available_mb(str(meminfo)) is None, "a machine that cannot say is not short"

    original = resources.available_mb
    try:
        resources.available_mb = lambda path="": 1024
        assert resources.short_of_memory(2048) == 1024
        assert resources.short_of_memory(1024) is None and resources.short_of_memory(0) is None
    finally:
        resources.available_mb = original


@case
def a_death_by_signal_is_told_from_a_failure_and_named():
    from ponos import resources

    def ended(code: int, **fields) -> session.Outcome:
        return session.Outcome(ok=False, blocked=False, session_id="s", summary="",
                               log=Path("x"), code=code, **fields)

    assert session.signalled(ended(-9)) and session.signalled(ended(137)) and session.signalled(ended(143))
    assert not session.signalled(ended(1)), "an ordinary failure is the session's own"
    assert not session.signalled(ended(-9, timed_out=True)), "the watchdog's kill is not a mystery"
    assert not session.signalled(ended(-15, stopped=True)), "nor is the console's Stop"
    assert resources.signal_name(-9).startswith("SIGKILL") and resources.signal_name(137).startswith("SIGKILL")
    assert resources.signal_name(143).startswith("SIGTERM") and resources.signal_name(1) == ""
    assert resources.network_error("fatal: unable to access 'x': Could not resolve host: github.com")
    assert not resources.network_error("remote: Permission denied")


@case
def a_runner_short_of_memory_starts_nothing_and_says_so_once():
    runner = _board_runner([], {})
    runner.config.runner.min_free_memory_mb = 2048
    runner._memory_warned = False
    said: list[str] = []
    runner.say = said.append
    from ponos import resources

    original = resources.available_mb
    try:
        resources.available_mb = lambda path="": 512
        assert not runner.room_for_a_session() and not runner.room_for_a_session()
        assert len(said) == 1 and "512" in said[0], said
        resources.available_mb = lambda path="": 4096
        assert runner.room_for_a_session()
        runner.config.runner.min_free_memory_mb = 0
        resources.available_mb = lambda path="": 1
        assert runner.room_for_a_session(), "zero switches the guard off"
    finally:
        resources.available_mb = original


@case
def a_ticket_this_run_holds_is_never_put_back():
    runner = _board_runner([_in_progress("p-held", None), _in_progress("p-signed", "ponos@laptop")], {})
    runner.client.columns = {"Runner": "rich_text"}
    runner._claimed = {"pheld", "psigned"}  # `Ticket.id`, dashes dropped
    with _state_home():
        assert runner.sweep() == 0
    assert runner.client.written == []


@case
def with_a_runner_column_only_this_hosts_tickets_come_back():
    """Unchanged where the board can say who took a ticket."""
    runner = _board_runner(
        [
            _in_progress("p-mine", "ponos@laptop"),
            _in_progress("p-theirs", "ponos@desktop"),
            _in_progress("p-unsigned", None),
        ],
        {},
    )
    runner.client.columns = {"Runner": "rich_text"}
    with _state_home():
        assert runner.sweep() == 1
    assert runner.client.written == [("p-mine", {"Status": "Ready"})]


@case
def a_publication_interrupted_on_a_board_without_a_runner_column_still_asks():
    runner = _board_runner([_in_progress("ppost", None)], {})
    with _state_home():
        state.claim("ppost", "Validated")
        assert runner.sweep() == 1
    assert runner.client.written == [("ppost", {"Status": "Blocked", "Blocage": "worktree.interrupted"})]


class _SchemaOnly(notion.Client):
    """A Notion client whose database has these columns, and whose PATCHes stay here."""

    def __init__(self, columns: dict[str, str], dropped=None):
        super().__init__("secret", dropped=dropped)
        self._columns = columns
        self.patched: list[dict] = []

    def schema(self, database_id: str) -> dict[str, str]:
        return dict(self._columns)

    def _request(self, method, path, body=None, **kwargs):
        self.patched.append(body or {})
        return {}


@case
def a_write_to_a_column_the_board_lacks_is_said_once_a_run():
    runner = _board_runner([], {})
    runner.quiet = False
    runner._unwritten = set()
    runner.client = _SchemaOnly({"Status": "status"}, dropped=runner._dropped)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for page in ("p1", "p2", "p3"):
            runner.client.update("db", page, {"Status": "In progress", "Runner": "ponos@laptop"})
            runner.client.update("db", page, {"Progress": "reading the code"})
    said = out.getvalue().splitlines()
    assert len(said) == 2, said
    assert "“Runner” is not a column of the board" in said[0]
    assert "a second one on this board would put back" in said[0], "with what it costs"
    assert "“Progress”" in said[1] and "while it runs" in said[1]
    assert all(body == {"properties": {"Status": {"status": {"name": "In progress"}}}}
               for body in runner.client.patched[::2]), "the status still goes through"
    runner._unwritten = set()  # what `tick` does: the next run says it again
    with contextlib.redirect_stdout(out):
        runner.client.update("db", "p4", {"Runner": "ponos@laptop"})
    assert out.getvalue().count("“Runner”") == 2


@case
def doctor_names_every_column_the_board_lacks_and_counts_it():
    from ponos.__main__ import _doctor_columns

    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    complete = {settings.prop(key): kinds_accepted[0] for key, (kinds_accepted, _) in store.COLUMNS.items()}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(complete, settings) == 0
    assert "missing" not in out.getvalue()

    lacking = {name: kind for name, kind in complete.items() if name not in ("Runner", "Progress")}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(lacking, settings) == 2
    said = re.sub(r"\x1b\[[0-9;]*m", "", out.getvalue())
    assert "✗ “Runner” missing — which machine took a ticket is not written" in said, said
    assert "✗ “Progress” missing — nothing says what a session is doing" in said, said
    assert "ponos init adds the missing ones" in said

    retyped = {**complete, "Cost": "rich_text"}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(retyped, settings) == 1
    assert "“Cost” is a rich_text, expected number" in out.getvalue()

    # The configuration of the 1st of October: `agent = "Agent"`, on a board
    # that has no column by that name — nor by the Runner one.
    renamed = C.Notion(properties={**C._DEFAULT_PROPERTIES, "agent": "Agent"})
    board = {name: kind for name, kind in complete.items() if name not in ("Agent", "Runner")}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(board, renamed) == 2  # the role column is “Agent” too
    assert "“Agent” missing — which machine took a ticket" in out.getvalue()


@case
def publishing_hands_the_page_as_it_stands_to_a_session_and_then_closes_it():
    """The whole road for a ticket with no branch: claim, publish, done."""
    runner = _board_runner([_reviewed("p-post", "Validated", None)], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None  # a ticket with no project never reaches it

    asked: list[str] = []

    def fake_run(prompt_text, **kwargs):
        asked.append(prompt_text)
        return session.Outcome(
            ok=True, blocked=False, session_id=kwargs.get("session_id", "s-1"),
            summary="publié sur le compte Instagram", log=Path("/tmp/none.jsonl"),
            seconds=90.0, turns=4,
        )

    original = session.run
    session.run = fake_run
    try:
        with _state_home():
            results = runner.deliver()
    finally:
        session.run = original

    # Claimed first, exactly as a run claims a ticket, and only then closed:
    # a second machine watching the board must not post the same thing twice.
    assert [values["Status"] for _, values in runner.client.written] == [
        "In progress", "Done",
    ]
    assert results and results[0]["kind"] == "delivery"

    prompt_text = asked[0]
    assert "Le post d'annonce" in prompt_text, "the page as it stands is what goes out"
    assert "publishing, not producing" in prompt_text
    assert "publié sur le compte Instagram" in runner.client.comments_written[0]


# -- the queue that refills itself --------------------------------------------


def _ready(page_id: str) -> notion.Page:
    return notion.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"Status": {"type": "status", "status": {"name": "Ready"}}},
    )


@case
def a_place_freed_mid_pass_is_filled_without_waiting_for_the_long_session():
    """The whole point of `max_concurrent`, and what a batch used to lose.

    A pass used to prepare the tickets that were ready at its first second and
    wait for every one of them. Measured on a real board: a pass started at
    14:04 with two tickets, one done in minutes and one still running at 14:23,
    while four tickets reached the ready column and not one agent was started —
    three free places and nothing in them.

    Here: two places, a long ticket and a short one, and a third ticket made
    ready while they run. It must start when the *short* one ends — which is
    what the long session witnesses on its way out.
    """
    third_started = threading.Event()
    started: list[str] = []
    witnessed: list[str] = []
    guard = threading.Lock()
    flight = peak = 0

    with _state_home():
        runner = _board_runner([_ready("p-long"), _ready("p-short")], {})
        runner.config.runner.max_concurrent = 2

        def prepare(ticket):
            return ticket_module.Job(
                ticket,
                projects.Project(name="", path=None),
                branch="",
                base="",
                workdir=Path(tempfile.mkdtemp()) / "doc",
            )

        def execute(job):
            nonlocal flight, peak
            name = job.ticket.page.id  # `Ticket.id` drops the dashes
            with guard:
                started.append(name)
                flight += 1
                peak = max(peak, flight)
            if name == "p-long":
                # Held until the third one has begun: what it sees when it
                # wakes is the whole point of the test.
                third_started.wait(10)
                with guard:
                    witnessed.extend(started)
            elif name == "p-short":
                # The board moves on while the long one is still in flight.
                runner.client._pages.append(_ready("p-third"))
            else:
                third_started.set()
            with guard:
                flight -= 1
            return {"ticket": name, "id": name, "status": "done"}

        runner.prepare, runner.execute = prepare, execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert "p-third" in witnessed, "the freed place was filled while the long one ran"
    assert len(witnessed) == 3, witnessed
    assert peak == 2, "never more than max_concurrent sessions at once"
    assert len(started) == 3, "and the pass ended only once the column was empty"
    assert results[0]["id"] == "p-short", "recorded as it ended, not as it was queued"
    assert sorted(result["id"] for result in results) == ["p-long", "p-short", "p-third"]


@case
def a_project_never_holds_more_places_than_max_concurrent_per_project():
    """Four tickets, three places: two of one project, then another's goes first.

    The third ticket of project A waits for a place of its own project although
    one is free, and the ticket behind it — project B's — is taken instead. It
    starts once a ticket of A has ended, and all four run.
    """
    guard = threading.Lock()
    inside: dict[str, int] = {}
    peak: dict[str, int] = {}
    order: list[str] = []
    projects_of = {"p-a1": "A", "p-a2": "A", "p-a3": "A", "p-b1": "B"}

    with _state_home():
        runner = _board_runner([_ready(name) for name in projects_of], {})
        runner.config.runner.max_concurrent = 3
        runner.config.runner.max_concurrent_per_project = 2
        runner.in_repository = lambda ticket: projects_of[ticket.page.id]

        def prepare(ticket):
            return ticket_module.Job(
                ticket,
                projects.Project(name="", path=None),
                branch="",
                base="",
                workdir=Path(tempfile.mkdtemp()) / "doc",
            )

        def execute(job):
            name = job.ticket.page.id
            project = projects_of[name]
            with guard:
                order.append(name)
                inside[project] = inside.get(project, 0) + 1
                peak[project] = max(peak.get(project, 0), inside[project])
            time.sleep(0.3)
            with guard:
                inside[project] -= 1
            return {"ticket": name, "id": name, "status": "done"}

        runner.prepare, runner.execute = prepare, execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert peak == {"A": 2, "B": 1}, peak
    assert sorted(result["id"] for result in results) == sorted(projects_of), results
    assert order.index("p-b1") < order.index("p-a3"), order


@case
def generated_files_are_declared_in_a_toml_file_and_read_as_globs():
    """`**` crosses folders, `*` does not, and a file that says nothing usable says nothing."""
    from ponos import generated

    rules = generated.parse(
        'generated = ["src/ponos/web/static/**", "*.lock", "docs/**/*.html"]\n'
        'build = " cd frontend && npm run build "\n'
    )
    assert rules.build == "cd frontend && npm run build"
    assert rules.covers("src/ponos/web/static/assets/console-1.js")
    assert rules.covers("src/ponos/web/static/index.html")
    assert rules.covers("uv.lock") and not rules.covers("sub/uv.lock")
    assert rules.covers("docs/a/b/c.html") and rules.covers("docs/c.html")
    assert not rules.covers("src/ponos/web/console.py")
    for broken in ("", "generated = [", 'generated = "dist/**"\nbuild = 3\n'):
        assert generated.parse(broken) == generated.Rules(), broken


@case
def max_concurrent_per_project_defaults_to_two_and_is_never_below_one():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "config.toml"
        assert C.Runner().max_concurrent_per_project == 2
        path.write_text("[runner]\nmax_concurrent_per_project = 0\n", encoding="utf-8")
        assert C.load(path).runner.max_concurrent_per_project == 1
        path.write_text("[runner]\nmax_concurrent_per_project = 3\n", encoding="utf-8")
        assert C.load(path).runner.max_concurrent_per_project == 3


@case
def a_place_that_was_never_filled_is_looked_at_before_a_session_ends():
    """The other half of the same fault, and the one that shows on a board.

    Tickets arrive one at a time: the first is started, the second place stays
    empty, and the pass then waited for the session in flight before reading the
    board again. Nothing else could read it either — the run lock is the pass's
    until it ends, and the timer meets it and leaves — so `max_concurrent = 2`
    ran one ticket at a time for as long as a ticket was in progress.

    Here: one long ticket, one free place, and a second ticket made ready while
    it runs. It must start while the long one is still in flight, without
    anything having ended.
    """
    second_started = threading.Event()
    started: list[str] = []
    witnessed: list[str] = []
    guard = threading.Lock()

    with _state_home():
        runner = _board_runner([_ready("p-long")], {})
        runner.config.runner.max_concurrent = 2
        # The cadence the pass looks at the board on, made a test's length.
        runner.config.runner.interval_seconds = 1
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            name = job.ticket.page.id
            with guard:
                started.append(name)
            if name == "p-long":
                runner.client._pages.append(_ready("p-second"))
                second_started.wait(10)
                with guard:
                    witnessed.extend(started)
            else:
                second_started.set()
            return {"ticket": name, "id": name, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert "p-second" in witnessed, "the empty place was filled with nothing ended"
    assert sorted(result["id"] for result in results) == ["p-long", "p-second"]


@case
def a_limit_caps_the_tickets_a_pass_takes_rather_than_the_column():
    """`--limit` names a number of tickets, and a queue that refills itself
    would otherwise run the whole board on a `--limit 1`."""
    with _state_home():
        runner = _board_runner([_ready("p-1"), _ready("p-2"), _ready("p-3")], {})
        runner.config.runner.max_concurrent = 4
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )
        runner.execute = lambda job: {"id": job.ticket.page.id, "status": "done"}
        results = runner._work(runner.queue()[0], 2, refill=True)

    assert sorted(result["id"] for result in results) == ["p-1", "p-2"]


@case
def a_pass_stops_filling_places_once_the_credits_run_out():
    """A queue that refills itself would otherwise walk the whole column into
    the same wall — one spent session, then every ticket on the board failed."""
    started: list[str] = []

    with _state_home():
        runner = _board_runner([_ready("p-1"), _ready("p-2"), _ready("p-3")], {})
        runner.config.runner.max_concurrent = 1
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            started.append(job.ticket.page.id)
            credits.hold(time.time() + 300)  # what a spent session leaves behind
            return {"id": job.ticket.page.id, "status": "waiting"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert started == ["p-1"], "the ticket in flight finished, and nothing else began"
    assert len(results) == 1


def _moved(page: notion.Page, status: str) -> None:
    """The page's status, changed the way a person or a run changes it."""
    page.properties["Status"] = {"type": "status", "status": {"name": status}}


@contextmanager
def _settling(seconds: float):
    """`board.SETTLE`, made a test's length."""
    from ponos import board as board_module

    before, board_module.SETTLE = board_module.SETTLE, seconds
    try:
        yield
    finally:
        board_module.SETTLE = before


@case
def a_new_ticket_is_taken_and_left_alone_once_its_run_has_moved_it():
    """The plain case, kept honest now that a finished ticket is no longer
    held out for the whole pass: once its status has moved, a reading of the
    board does not bring it back."""
    runs: list[str] = []
    with _state_home(), _settling(0.1):
        page = _ready("p-new")
        runner = _long_runner([page, _ready("p-long")])
        runner.config.runner.max_concurrent = 2

        def execute(job):
            name = job.ticket.page.id
            runs.append(name)
            if name == "p-new":
                _moved(page, "In review")
            else:
                time.sleep(2.5)  # two looks at the board while it runs
            return {"id": name, "status": "done"}

        runner.execute = execute
        runner._work(runner.queue()[0], None, refill=True)

    assert sorted(runs) == ["p-long", "p-new"], runs


@case
def a_ticket_played_by_this_pass_then_made_ready_again_is_played_again():
    """The fault of the 9th of October, on the real board: two Lead Finder
    tickets run at 22:53 by a pass that was still going at 23:50, blocked on
    their merge, moved back to ready by hand — and skipped by every reading of
    the column, because the pass held out every ticket it had *ever* started,
    while each new ticket went straight through."""
    runs: list[str] = []
    again = threading.Event()
    with _state_home(), _settling(0.1):
        page = _ready("p-again")
        runner = _long_runner([page, _ready("p-long")])
        runner.config.runner.max_concurrent = 2

        def execute(job):
            name = job.ticket.page.id
            runs.append(name)
            if name == "p-again":
                if runs.count("p-again") == 1:
                    _moved(page, "Blocked")
                else:
                    _moved(page, "In review")
                    again.set()
            else:
                time.sleep(0.5)
                _moved(page, "Ready")  # somebody asks for it again
                again.wait(10)
            return {"id": name, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert again.is_set(), "taken again by the pass that had already run it"
    assert runs.count("p-again") == 2, runs
    assert [result["id"] for result in results].count("p-again") == 2


@case
def a_ticket_still_in_a_session_of_this_pass_is_not_run_beside_it():
    """A live claim. Moved back to ready while its session runs — or served as
    ready by a Notion that has not caught up — the ticket waits for that
    session, says why on its card, and is played again once it is over."""
    runs: list[str] = []
    flying = peak = 0
    noted: list[dict] = []
    guard = threading.Lock()
    with _state_home(), _settling(0.1):
        page = _ready("p-one")
        runner = _long_runner([page])
        runner.config.runner.max_concurrent = 2

        def execute(job):
            nonlocal flying, peak
            with guard:
                runs.append(job.ticket.page.id)
                flying += 1
                peak = max(peak, flying)
            if len(runs) == 1:
                time.sleep(2.5)  # two looks at a column that still says ready
                noted.append(state.held())
            else:
                _moved(page, "In review")
            with guard:
                flying -= 1
            return {"id": job.ticket.page.id, "status": "done"}

        runner.execute = execute
        runner._work(runner.queue()[0], None, refill=True)
        left = state.held()
        assert runs == ["p-one"], "not beside itself, and not straight after either"
        # The next pass — the timer's — finds it still ready, and plays it.
        runner._work(runner.queue()[0], None, refill=True)

    assert peak == 1, "never two sessions on one ticket"
    assert runs == ["p-one", "p-one"], "and played again once the first was over"
    assert noted == [{"pone": ("running", "")}], noted
    assert left == {}, "the record goes with the pass"


@case
def a_ready_ticket_with_every_place_taken_says_so_once():
    said: list[str] = []
    with _state_home():
        runner = _board_runner([_ready("p-1"), _ready("p-2")], {})
        runner.say = said.append
        queued = runner.queue()[0][1:]
        runner.explain(queued, 1)
        runner.explain(queued, 1)
        assert state.held() == {"p2": ("places", "1")}
        runner.explain([], 1, done=True)
        assert state.held() == {}
    assert said == ["  … p-2 — waiting: all 1 place(s) taken — it starts at the next free one"]


@case
def an_orphan_claim_is_let_go_of_by_the_sweep():
    """A note of a claim whose ticket is no longer in progress — moved by hand,
    or its run gone without a word — is dropped; one still in progress is not."""
    live = _in_progress("p-live", None)
    live.raw["last_edited_time"] = datetime.now(timezone.utc).isoformat()
    runner = _board_runner([live], {})
    with _state_home():
        state.claim("plive", "Validated")
        state.claim("pgone", "Validated")
        assert runner.sweep() == 0, "too recent to be called abandoned"
        assert state.claims() == {"plive": "Validated"}


@case
def a_ready_card_always_says_what_it_is_waiting_for():
    from ponos.web import board as web_board

    now = datetime(2026, 10, 9, 23, 50, tzinfo=timezone.utc)
    card = {"id": "p1", "column": "ready", "scheduled": ""}

    def held(ticket=card, noted=None, passing=True, timer=True, waits=None):
        found = web_board.held(
            ticket, noted or {}, passing=passing, timer=timer, waits=waits, now=now
        )
        return found.get("reason"), found.get("detail")

    assert web_board.held({**card, "column": "review"}, {}, passing=True, timer=True) == {}
    later = {**card, "scheduled": "2026-10-10T09:00+02:00"}
    assert held(later, waits={"credits": "04:00"}) == ("date", "2026-10-10T09:00+02:00")
    assert held(waits={"credits": "04:00", "reserve": ""}) == ("credits", "04:00")
    assert held(noted={"p1": ("running", "")}) == ("running", "")
    assert held(noted={"p1": ("places", "2")}) == ("places", "2")
    assert held() == ("pass", "")
    assert held(noted={"p1": ("running", "")}, passing=False) == ("next", ""), "a dead pass's note"
    assert held(passing=False, timer=False) == ("timer", "")


# -- a validated ticket never waits for a session ----------------------------


def _long_runner(pages: list[notion.Page]) -> Runner:
    """A runner whose tickets are prepared for free and run for as long as asked."""
    runner = _board_runner(pages, {})
    # The cadence the pass looks at the board on, made a test's length.
    runner.config.runner.interval_seconds = 1
    runner.prepare = lambda ticket: ticket_module.Job(
        ticket,
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )
    return runner


@case
def a_pull_request_validated_mid_pass_is_merged_without_waiting_for_the_session():
    """The fault on a real board: a column full of work you have accepted, and
    a two-hour session it has nothing to do with standing in front of it.

    Here the single place is taken for as long as the merge has not happened, so
    the only way out of the test is the pass looking at the validated column
    while its pool is full. The merge itself costs no place: two `gh` calls in
    the pass's own thread.
    """
    merges: list[str] = []
    merged = threading.Event()

    with _state_home():
        runner = _long_runner([_ready("p-long")])
        runner.config.runner.max_concurrent = 1  # every place taken, throughout

        def execute(job):
            # Validated by you while the session runs, as it happens on a board.
            runner.client._pages.append(
                _reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")
            )
            merged.wait(10)
            # Two more looks at the column, which still answers "Validated":
            # the fake board only remembers what was written, it does not move.
            time.sleep(2.2)
            return {"id": job.ticket.page.id, "status": "done"}

        def merge(url: str, method: str = "squash", accounts=None) -> str:
            merges.append(url)
            merged.set()
            return "merged"

        runner.execute = execute
        with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge):
            results = runner._work(runner.queue()[0], None, refill=True)

    assert merged.is_set(), "merged while the session was still running"
    assert merges == ["https://github.com/x/y/pull/1"], "and merged once, not at every look"
    assert sorted(result["id"] for result in results) == ["p-long", "pvalidated"]
    assert ("p-validated", {"Status": "Done"}) in runner.client.written


@case
def a_publication_validated_mid_pass_takes_the_next_free_place():
    """A publication is a session, so it waits for a place — that one, not the
    end of the pass. And it takes it before a ticket nobody has read yet."""
    published: list[str] = []
    out = threading.Event()

    with _state_home():
        runner = _long_runner([_ready("p-long")])
        runner.config.runner.max_concurrent = 2  # one place taken, one free
        runner._project_of = lambda ticket: projects.Project(name="Blog", path=None)

        def publish(ticket, project):
            published.append(ticket.id)
            out.set()
            return {"ticket": ticket.title, "id": ticket.id, "status": "done"}

        def execute(job):
            runner.client._pages.append(_reviewed("p-post", "Validated", None))
            out.wait(10)
            return {"id": job.ticket.page.id, "status": "done"}

        runner._publish, runner.execute = publish, execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert published == ["ppost"], "published while the long session ran"
    assert sorted(result["id"] for result in results) == ["p-long", "ppost"]


@case
def a_pass_that_refills_nothing_leaves_the_validated_column_alone():
    """A named ticket and a dry run take nothing off the board — that column
    included, which `tick` has already read for them."""
    with _state_home():
        runner = _long_runner([_ready("p-one")])
        runner.client._pages.append(_reviewed("p-post", "Validated", None))
        runner._publish = lambda ticket, project: (_ for _ in ()).throw(
            AssertionError("published by a pass that refills nothing")
        )
        runner.execute = lambda job: {"id": job.ticket.page.id, "status": "done"}
        results = runner._work(runner.queue()[0], None, refill=False)

    assert [result["id"] for result in results] == ["p-one"]


# -- naming a ticket nobody titled -------------------------------------------


class _NamelessClient:
    """One ticket, its content, and everything written back onto it."""

    def __init__(self, body: str, refuse: bool = False):
        self._body = body
        self._refuse = refuse
        self.written: list[dict] = []

    def schema(self, database_id: str) -> dict[str, str]:
        # Not "Name": the title column is called whatever Notion was told.
        return {"Titre": "title", "Status": "status"}

    def title_property(self, database_id: str) -> str:
        return notion.Client.title_property(self, database_id)  # the real lookup

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._body

    def comments(self, page_id: str) -> list[notion.Comment]:
        return []

    def page(self, page_id: str) -> notion.Page:
        # The ticket is held by the test, not here: a page this cannot read is
        # a status written as it always was — see `Reports._still`.
        raise notion.NotionError(f"GET /pages/{page_id}: 404 not held by this fake")

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        if self._refuse and "Titre" in values:
            raise notion.NotionError("PATCH /pages/x: 403 insufficient permissions")
        self.written.append(values)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        pass


class _OneRepository:
    """A resolver for a board whose single project is a repository."""

    def resolve(self, client, page_id: str, *, clone: bool = False) -> projects.Project:
        return projects.Project(name="ponos", path=Path("/repo"))


def _nameless(title: str, body: str, refuse: bool = False):
    """A Runner about to prepare one ticket, with Notion replaced."""
    page = notion.Page(
        id="3ce451680af481bc9b66f4d875f74ff5",
        url="https://notion.so/t",
        title=title,
        properties={
            "Titre": {"type": "title", "title": [{"plain_text": title}]},
            "Project": {"type": "relation", "relation": [{"id": "p-runner"}]},
        },
    )
    runner = _board_runner([page], {})
    runner.client = _NamelessClient(body, refuse)
    runner.config.runner.base_branch = "main"  # so git is never asked anything
    runner.resolver = _OneRepository()
    return runner, ticket_module.Ticket(page)


@contextmanager
def _naming_session(answer: str, missing: bool = False):
    """The one-line session that names a ticket, replaced by what it said."""
    asked: list[str] = []

    def fake_run(prompt_text, **kwargs):
        asked.append(prompt_text)
        if missing:
            raise FileNotFoundError("claude not found in PATH")
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s-name",
            summary="",
            log=Path("/tmp/none.jsonl"),
            answer=answer,
        )

    original = session.run
    session.run = fake_run
    try:
        yield asked
    finally:
        session.run = original


@case
def a_ticket_with_no_title_is_named_from_what_it_says():
    """And named before the branch, which is what the title is first used for."""
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    with _state_home(), _naming_session("Réparer le bandeau blanc de la console") as asked:
        job = runner.prepare(ticket)

    assert asked and "Le bandeau de la console" in asked[0], "it names from the content"
    assert runner.client.written[0] == {"Titre": "Réparer le bandeau blanc de la console"}
    assert ticket.title == "Réparer le bandeau blanc de la console"
    assert job.branch == "ticket/reparer-le-bandeau-blanc-de-la-console-75f74ff5"


@case
def a_project_found_by_a_fallback_says_so_on_the_ticket():
    """The ticket runs, and the comment carries which declaration to correct —
    the alternative is a page that stays wrong for as long as the fallback holds."""

    class _StaleRepository:
        def resolve(self, client, page_id: str, *, clone: bool = False) -> projects.Project:
            return projects.Project(
                name="ponos",
                path=Path("/repo"),
                note="Repository found by its origin remote, x/y, but a more explicit "
                "declaration is wrong: /old, from the project's Path property, is not "
                "a git repository. Correct it: the fallback is what its tickets run on.",
            )

    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    runner.resolver = _StaleRepository()
    with _state_home(), _naming_session("") as asked:
        job = runner.prepare(ticket)
    assert job is not None and job.project.path == Path("/repo"), "the ticket runs"
    assert len(job.notes) == 1 and "from the project's Path property" in job.notes[0]


@case
def a_repository_the_run_had_to_fetch_is_said_on_the_ticket():
    """A ticket running on a folder nobody made by hand deserves the sentence
    that says where it came from — and a dry run downloads nothing."""

    class _Fetching:
        def __init__(self) -> None:
            self.asked: list[bool] = []

        def resolve(self, client, page_id: str, *, clone: bool = False) -> projects.Project:
            self.asked.append(clone)
            return projects.Project(
                name="ponos",
                path=Path("/repo"),
                cloned="`Salva/site` was nowhere under ~/workspace — cloned into /repo.",
            )

    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    runner.resolver = resolver = _Fetching()
    with _state_home(), _naming_session(""):
        job = runner.prepare(ticket)
    assert resolver.asked == [True], "a run about to work on a ticket asks for the clone"
    assert job is not None and len(job.notes) == 1 and "cloned into" in job.notes[0]

    runner.dry_run = True
    with _state_home(), _naming_session(""):
        runner.prepare(ticket)
    assert resolver.asked == [True, False], "a dry run says what it would do, and fetches nothing"


@case
def a_ticket_that_already_has_a_title_costs_nothing_and_keeps_it():
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    with _state_home(), _naming_session("Un titre que personne n'a demandé") as asked:
        job = runner.prepare(ticket)

    assert asked == [], "the common case must not pay for a session"
    assert ticket.title == "Retirer le shader"
    assert all("Titre" not in values for values in runner.client.written)
    assert job.branch == "ticket/retirer-le-shader-75f74ff5"


@case
def a_ticket_with_neither_a_title_nor_content_is_asked_about_rather_than_named():
    """Nothing to name from is nothing to invent from: it stays the old question."""
    runner, ticket = _nameless("", "## Ce qu'il faut faire\n## Comment on saura\n")
    with _state_home(), _naming_session("Inventé de toutes pièces") as asked:
        job = runner.prepare(ticket)

    assert job is None and asked == []
    assert runner.client.written == [{"Status": "Blocked", "Blocage": "ticket.empty"}]


@case
def a_naming_that_fails_falls_back_on_the_first_line_of_the_content():
    """No claude on the PATH, and the ticket is still named — and still runs."""
    runner, ticket = _nameless(
        "",
        "## Ce qu'il faut faire\n"
        "Retirer le shader du bandeau de la console, il coûte 12 % de CPU pour rien.",
    )
    with _state_home(), _naming_session("", missing=True):
        job = runner.prepare(ticket)

    # The first line that says something, cut on a word rather than mid-word.
    assert runner.client.written[0] == {
        "Titre": "Retirer le shader du bandeau de la console, il coûte 12 %…"
    }
    assert job.branch.startswith("ticket/retirer-le-shader-du-bandeau")


@case
def a_title_notion_refuses_leaves_the_ticket_to_run_under_the_default_label():
    """A name is a comfort. Losing it must not cost the ticket its run."""
    runner, ticket = _nameless("", "Le bandeau reste blanc au chargement.", refuse=True)
    with _state_home(), _naming_session("Réparer le bandeau blanc"):
        job = runner.prepare(ticket)

    assert job is not None
    # Kept in memory it would name a branch the board cannot show.
    assert ticket.title == "(untitled ticket)"
    assert job.branch == "ticket/untitled-ticket-75f74ff5"


# -- the type of a ticket ----------------------------------------------------


@case
def a_classification_is_read_out_of_whatever_the_session_wrapped_it_in():
    said = 'Voici :\n```json\n{"type": "Publication", "reason": "Un  post.", ' \
        '"confidence": "HIGH", "alternative": "writing"}\n```'
    guess = kinds.parse(said)
    assert (guess.kind, guess.confidence, guess.alternative) == ("publication", "high", "writing")
    assert guess.reason == "Un post."
    assert kinds.parse("je ne sais pas") == kinds.Guess(), "no object is no type"
    unknown = kinds.parse('{"type": "deploy", "confidence": "sure"}')
    assert unknown.kind == "" and unknown.confidence == "low", "outside the four is nothing"
    same = kinds.parse('{"type": "code", "confidence": "high", "alternative": "code"}')
    assert same.alternative == "", "hesitating with itself is not hesitating"


@case
def a_doubt_is_never_settled_by_running_the_ticket():
    """Too unsure, or unsure between a harmless type and one that acts on the
    world: either way it is a question — and in doubt, the careful type."""
    sure = kinds.Guess("writing", "", "high", "")
    assert kinds.doubt(sure) == ""
    assert kinds.doubt(kinds.Guess()) == "unknown"
    assert kinds.doubt(kinds.Guess("code", "", "low", "")) == "unsure"
    assert kinds.doubt(kinds.Guess("code", "", "medium", ""), "high") == "unsure"
    assert kinds.doubt(kinds.Guess("code", "", "low", ""), "low") == ""
    assert kinds.doubt(kinds.Guess("writing", "", "high", "publication")) == "hesitant"
    assert kinds.doubt(kinds.Guess("external", "", "high", "code")) == "hesitant"
    assert kinds.doubt(kinds.Guess("code", "", "high", "writing")) == "", (
        "hesitating between two harmless types is not a reason to stop"
    )
    assert kinds.prudent("writing", "publication") == "publication"
    assert kinds.prudent("code", "external") == "external"
    assert kinds.prudent("code", "writing") == "code"


@case
def a_doubt_between_code_and_another_type_takes_the_one_that_needs_no_commit():
    """An audit, a deployment, a setting in production: about code, not code.

    Settled rather than asked, whatever the confidence — and said, so the
    choice can be corrected where it was made.
    """
    for kind, alternative, taken in (
        ("code", "external", "external"),
        ("external", "code", "external"),
        ("code", "writing", "writing"),
        ("writing", "code", "writing"),
        ("code", "publication", "publication"),
    ):
        settled = kinds.settle(kinds.Guess(kind, "", "low", alternative))
        assert (settled.kind, settled.settled, settled.alternative) == (taken, "code", ""), settled
        assert kinds.doubt(settled) == "", "settled is not a doubt"
    plain = kinds.Guess("code", "", "low", "")
    assert kinds.settle(plain) is plain and kinds.doubt(plain) == "unsure", (
        "unsure of code alone is still a question"
    )
    risky = kinds.Guess("writing", "", "high", "publication")
    assert kinds.settle(risky) is risky and kinds.doubt(risky) == "hesitant"
    asked = kinds.prompt("Audit", "Ne code rien.", project="Site", repository=True)
    assert "An audit, a review, a check or a verification is writing" in asked
    assert "Deploying or redeploying" in asked
    assert "Between code and another type, choose the other one" in asked


@case
def a_ticket_settled_off_code_says_so_on_the_ticket():
    runner, ticket = _typed(body="Vérifie que la prod répond, ne code rien.")
    answer = '{"type": "code", "reason": "Peut-être un correctif.", "confidence": "low", ' \
        '"alternative": "external"}'
    with _state_home(), _naming_session(answer):
        job = runner.prepare(ticket)

    assert job is not None and job.kind == "external" and not job.project.is_code
    assert runner.client.written[0] == {"Type": "Action externe"}, runner.client.written
    said = runner.client.said[0]
    assert "Code" in said and "commit" in said, said


@case
def a_report_of_work_done_outside_the_repository_is_told_from_a_code_change():
    from ponos import execution

    for outside in (
        "Variable SMTP_HOST ajoutée dans Dokploy, application redéployée.",
        "6 bugs et 13 idées créés dans Notion.",
        "Enregistrement DNS ajouté chez OVH, le domaine répond.",
        "Redeployed the app with the new environment variable.",
    ):
        assert execution._done_elsewhere(outside), outside
    for code in (
        "J'ai corrigé le fichier de configuration puis redéployé dans Dokploy.",
        "Changed src/app.ts and redeployed.",
        "Le titre de la page est corrigé.",
        "",
    ):
        assert not execution._done_elsewhere(code), code
    assert execution._report("Fait.\n\n**RESULT: ok — fait**") == "Fait."


@case
def the_classification_is_told_whether_there_is_a_repository():
    asked = kinds.prompt("Le DNS", "Ajoute un CNAME.", project="Site", repository=False,
                         comments=["the ticket's author: c'est chez Hostinger"])
    assert "no code repository: it cannot be a code ticket" in asked
    assert "Ajoute un CNAME." in asked and "c'est chez Hostinger" in asked
    assert "belongs to no project" in kinds.prompt("x", "", project="", repository=False)
    assert "has a code repository" in kinds.prompt("x", "", project="Site", repository=True)


@case
def a_board_spells_the_types_in_either_language():
    """A board built by hand in French reads as typed, not as four unknown words."""
    settings = C.Notion()
    assert settings.kind_of("Rédaction") == "writing"
    assert settings.kind_of(" action externe ") == "external"
    assert settings.kind_of("Code") == "code" and settings.kind_of("Writing") == "writing"
    assert settings.kind_of("Urgent") == "" and settings.kind_of("") == ""
    named = C.Notion(types={"writing": "Texte"})
    assert named.kind_of("Texte") == "writing"
    assert named.kind_of("Rédaction") == "", "a name the file chose is the only one read"


@case
def a_type_somebody_chose_takes_a_repository_ticket_off_its_repository():
    project = projects.Project(name="Site", path=Path("/repo"))
    assert kinds.worked_in(project, "code") is project
    assert kinds.worked_in(project, "") is project
    for kind in ("writing", "external", "publication"):
        assert not kinds.worked_in(project, kind).is_code, kind
        assert kinds.worked_in(project, kind).name == "Site"
    assert "prepare it, do not publish it" in prompt.kind("publication")
    assert "Stop at the first doubt" in prompt.kind("external")
    assert prompt.kind("writing") == "" and prompt.kind("code") == ""
    assert "/repo: read it" in prompt.kind("writing", Path("/repo"))


@case
def a_prompt_file_older_than_the_types_still_says_do_not_publish():
    """A template of your own has no `{kind}`: the rule is added at its end."""
    built = prompt.build(
        "Old template — {title}\n{body}", project="", title="Post", body="Un post.",
        repo="/tmp/x", branch="", base="", url="u", kind=prompt.kind("publication"),
    )
    assert built.startswith("Old template — Post")
    assert built.rstrip().endswith(prompt.PREPARE.rstrip())
    document = prompt.build(
        prompt.DOCUMENT, project="", title="Post", body="Un post.", repo="/tmp/x",
        branch="", base="", url="u", kind=prompt.kind("publication"),
    )
    assert document.index("do not publish it") < document.index("# What is expected")
    plain = prompt.build(
        prompt.DOCUMENT, project="", title="Post", body="Un post.", repo="/tmp/x",
        branch="", base="", url="u",
    )
    assert "- Notion ticket: u\n\n# What is expected" in plain, "no type, no change"


@case
def every_session_reads_what_it_may_do_alone():
    """The policy is in the prompt of each ticket, the list written or the default."""
    common = dict(project="", title="T", body="b", repo="/tmp/x", branch="", base="", url="u")
    for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.DELIVERY, prompt.RESOLVE):
        text = prompt.build(template, **common, allowed=["relancer une CI"], ask=["modifier un DNS"])
        assert "You do these without asking:\n- relancer une CI" in text, template[:30]
        assert "before these" in text and "- modifier un DNS" in text
        assert text.index("# What you may do alone") < text.index("# Context") or "{agent}" not in template
        assert "access.sudo" in text and "access.credentials" in text
    old = prompt.build("Old template — {title}", **common, allowed=["relancer une CI"])
    assert "- relancer une CI" in old, "a prompt file of your own gets it at its end"
    nothing = prompt.build(prompt.DEFAULT, **common)
    assert "You do these without asking" not in nothing and "access.sudo" in nothing
    assert "# What you may do alone" not in prompt.conversation(
        prompt.CONVERSATION, project="", title="T", body="b", where="w", url="u", message="m"
    )

    defaults = C.Permissions()
    assert any("dokploy.cardona.digital" in rule for rule in defaults.allowed)
    for owner in ("SalvadorCardona", "hermez-agency"):
        assert any("release" in rule and owner in rule for rule in defaults.allowed), owner
        assert any("cloner" in rule and owner in rule for rule in defaults.allowed), owner
    assert "another SalvadorCardona or hermez-agency repository" in " ".join(
        prompt.PERMISSIONS.split()
    ), "a ticket aimed at a migrated repository is not a question either"
    assert "toute dépense" in defaults.ask and "modifier un DNS" in defaults.ask
    assert C.load(_saved()[0]).permissions == defaults


@case
def the_permissions_are_edited_in_the_settings_and_an_empty_list_is_an_answer():
    path, config = _saved()
    drawn = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert drawn["permissions.allowed"]["fallback"] == list(C.ALLOWED)
    assert drawn["permissions.ask"]["value"] is None
    web_settings.save(config, {"settings": {
        "permissions.allowed": [" relancer   une CI ", "", "fusionner une PR validée"],
        "permissions.ask": [],
    }})
    saved = C.load(path).permissions
    assert saved.allowed == ("relancer une CI", "fusionner une PR validée")
    assert saved.ask == (), "emptied is written, not brought back to the default"
    web_settings.save(config, {"settings": {"permissions.ask": None}})
    assert C.load(path).permissions.ask == C.ASK
    try:
        web_settings.save(config, {"settings": {"permissions.allowed": "relancer une CI"}})
        raise AssertionError("a string is not a list")
    except ValueError:
        pass


@case
def a_ticket_that_needs_sudo_blocks_with_the_commands_and_no_yes_no():
    answer = (
        "Tailscale needs root.\n"
        "DONE: nothing\n"
        "WHY: je n'ai pas le mot de passe sudo\n"
        "QUESTION: Lance ces commandes puis réponds « fait »\n"
        "MODE: yes-no\n"
        "CODE: access.sudo\n"
        "COMMAND: sudo apt install -y tailscale\n"
        "COMMAND: `sudo tailscale up`\n"
        "RESULT: blocked — sudo demande un mot de passe"
    )
    asked = question.parse(answer)
    assert asked.code == "access.sudo" and asked.mode == "free", "never a yes-no"
    assert asked.commands == ["sudo apt install -y tailscale", "sudo tailscale up"]
    lines = voice.Voice("fr").question(asked)
    assert lines[1] == "`access.sudo`"
    assert lines[2:4] == ["`sudo apt install -y tailscale`", "`sudo tailscale up`"]
    assert lines[-1].startswith("Lance ces commandes") and "oui" not in lines[-1].lower()
    unknown = question.parse("QUESTION: ok ?\nMODE: yes-no\nCODE: whatever\nCOMMAND: rm -rf /")
    assert unknown.code == "" and unknown.commands == [] and unknown.mode == "yes-no"


class _TypedClient(_NamelessClient):
    """The same ticket, on a board that has a Type column — in French."""

    def __init__(self, body: str):
        super().__init__(body)
        self.said: list[str] = []

    def schema(self, database_id: str) -> dict[str, str]:
        return {**super().schema(database_id), "Type": "select"}

    def options(self, database_id: str, name: str) -> list[str]:
        return ["Code", "Rédaction", "Action externe", "Publication"] if name == "Type" else []

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.said.append(text)


def _typed(kind: str = "", body: str = "Poste l'annonce de la v2 sur LinkedIn."):
    runner, ticket = _nameless("Annoncer la v2", body)
    runner.client = _TypedClient(body)
    if kind:
        ticket.page.properties["Type"] = {"type": "select", "select": {"name": kind}}
    return runner, ticket


@case
def a_ticket_with_no_type_is_classified_before_it_runs():
    """Written on the page in the board's own spelling, and explained in a comment."""
    runner, ticket = _typed()
    answer = '{"type": "writing", "reason": "Il demande un texte.", "confidence": "high", ' \
        '"alternative": ""}'
    with _state_home(), _naming_session(answer) as asked:
        job = runner.prepare(ticket)

    assert len(asked) == 1 and "say what kind of ticket it is" in asked[0]
    assert runner.client.written[0] == {"Type": "Rédaction"}, runner.client.written
    assert runner.client.said[0].startswith("🏷️") and "Il demande un texte." in runner.client.said[0]
    assert job is not None and job.kind == "writing"
    assert not job.project.is_code and job.reference == Path("/repo"), (
        "a text is not worked in the repository, only allowed to read it"
    )


@case
def a_type_somebody_chose_is_never_classified_again():
    runner, ticket = _typed("Code")
    with _state_home(), _naming_session('{"type": "publication", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)

    assert asked == [], "a chosen type costs no session"
    assert all("Type" not in values for values in runner.client.written)
    assert job is not None and job.kind == "code" and job.project.is_code


@case
def a_classification_that_is_not_sure_blocks_the_ticket_with_the_question():
    """Nothing claimed, no type written — the column is left for you to fill."""
    runner, ticket = _typed()
    answer = '{"type": "writing", "reason": "Rédiger, ou publier ?", "confidence": "high", ' \
        '"alternative": "publication"}'
    with _state_home(), _naming_session(answer):
        job = runner.prepare(ticket)

    assert job is None
    assert runner.client.written == [{"Status": "Blocked", "Blocage": "ticket.kind-unsure"}], runner.client.written
    question = runner.client.said[-1]
    assert "Rédaction or Publication?" in question and "Rédiger, ou publier ?" in question
    assert "I would take Publication" in question, "in doubt, the careful one"

    runner, ticket = _typed()
    with _state_home(), _naming_session('{"type": "code", "confidence": "low"}'):
        assert runner.prepare(ticket) is None
    assert runner.client.written == [{"Status": "Blocked", "Blocage": "ticket.kind-unsure"}]

    runner, ticket = _typed()
    with _state_home(), _naming_session("", missing=True):
        assert runner.prepare(ticket) is None, "no answer at all is the deepest doubt"


@case
def a_board_without_the_column_or_the_setting_runs_tickets_as_before():
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    with _state_home(), _naming_session('{"type": "writing", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.kind == "" and job.project.is_code

    runner, ticket = _typed()
    runner.config.runner.classify = False
    with _state_home(), _naming_session('{"type": "writing", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.kind == "" and job.project.is_code


# -- the sub-type of a code ticket --------------------------------------------


class _SubtypedClient(_TypedClient):
    """A board with a Type column and a Sous-type one."""

    def schema(self, database_id: str) -> dict[str, str]:
        return {**super().schema(database_id), "Sous-type": "select"}


def _subtyped(title: str, *, kind: str = "Code", subtype: str = "", body: str = "Le bouton ne répond plus."):
    runner, ticket = _nameless(title, body)
    runner.client = _SubtypedClient(body)
    if kind:
        ticket.page.properties["Type"] = {"type": "select", "select": {"name": kind}}
    if subtype:
        ticket.page.properties["Sous-type"] = {"type": "select", "select": {"name": subtype}}
    return runner, ticket


def _subtype_written(runner) -> list[str]:
    return [values["Sous-type"] for values in runner.client.written if "Sous-type" in values]


@case
def a_prefix_says_the_sub_type_without_asking_anybody():
    for title, key in (
        ("[Bug] Le bouton ne répond plus", "bug"),
        ("Ponos — [Feature] Un badge sur la carte", "feature"),
        ("[UX] [Amélioration] Des libellés plus clairs", "improvement"),
        ("[Ops] Monter la version de Node", "chore"),
        ("[Refactor] Découper runner.py", "refactor"),
        ("[Perf] Le board s'ouvre en 80 ms", "perf"),
        ("[Docs] Le README", "docs"),
        ("[Sécurité] Le token fuit dans les logs", "security"),
        ("[security] same, in English", "security"),
    ):
        assert subtypes.from_prefix(title) == key, title
    assert subtypes.from_prefix("[UX] Une carte plus lisible") == "", "a domain says nothing"
    assert subtypes.from_prefix("Le bouton ne répond plus") == ""

    runner, ticket = _subtyped("[Bug] Le bouton ne répond plus")
    with _state_home(), _naming_session('{"subtype": "feature", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [], "a prefix costs no session"
    assert job is not None and job.subtype == "bug"
    assert _subtype_written(runner) == ["Bug"]


@case
def a_sub_type_without_a_prefix_is_deduced_by_the_light_model():
    runner, ticket = _subtyped("Le bouton Envoyer ne répond plus")
    answer = '{"subtype": "bug", "reason": "Il ne marche plus.", "confidence": "high"}'
    with _state_home(), _naming_session(answer) as asked:
        job = runner.prepare(ticket)
    assert len(asked) == 1 and "what kind of change it is" in asked[0], asked
    assert job is not None and job.subtype == "bug"
    assert _subtype_written(runner) == ["Bug"]
    assert any("Il ne marche plus." in note for note in job.notes), job.notes

    # With no type either, the one session says both.
    runner, ticket = _subtyped("Le bouton Envoyer ne répond plus", kind="")
    answer = '{"type": "code", "reason": "Un correctif.", "confidence": "high", ' \
        '"alternative": "", "subtype": "perf", "subtype_confidence": "medium"}'
    with _state_home(), _naming_session(answer) as asked:
        job = runner.prepare(ticket)
    assert len(asked) == 1 and '"subtype"' in asked[0], "one session for the type and the sub-type"
    assert job is not None and job.kind == "code" and job.subtype == "perf"
    assert _subtype_written(runner) == ["Perf"]


@case
def a_sub_type_in_doubt_is_an_improvement_and_the_report_says_so():
    runner, ticket = _subtyped("Revoir le bouton Envoyer")
    with _state_home(), _naming_session('{"subtype": "bug", "confidence": "low"}'):
        job = runner.prepare(ticket)
    assert job is not None and job.subtype == "improvement", "a doubt never blocks"
    assert _subtype_written(runner) == ["Amélioration"]
    assert any("Sous-type" in note and "Amélioration" in note for note in job.notes), job.notes

    runner, ticket = _subtyped("Revoir le bouton Envoyer")
    with _state_home(), _naming_session("", missing=True):
        job = runner.prepare(ticket)
    assert job is not None and job.subtype == "improvement"
    assert _subtype_written(runner) == [], "no answer at all: nothing written, asked again next time"


@case
def a_sub_type_somebody_wrote_is_never_overwritten():
    runner, ticket = _subtyped("[Bug] Le README", subtype="Docs")
    with _state_home(), _naming_session('{"subtype": "bug", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and _subtype_written(runner) == []
    assert job is not None and job.subtype == "docs", "the column wins over the prefix"

    runner, ticket = _subtyped("[Bug] Annoncer la v2", kind="Rédaction")
    with _state_home(), _naming_session("{}") as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.subtype == "" and _subtype_written(runner) == [], (
        "ignored on the other types"
    )

    runner, ticket = _nameless("Le bouton ne répond plus", "x")
    with _state_home(), _naming_session('{"subtype": "bug", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.subtype == "", "a board without the column asks nobody"


@case
def a_sub_type_is_the_developers_word_in_every_language():
    """« Feature » in French too, not « Fonctionnalité »: one label, no entry in french.ts.

    The French words it used to be shown as are still understood, in a title or
    an answer — only what the console shows changed, not what is read.
    """
    dictionary = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    assert [subtype.label for subtype in subtypes.SUBTYPES] == [
        "Bug", "Feature", "Improvement", "Chore", "Refactor", "Perf", "Docs", "Security",
    ]
    for subtype in subtypes.SUBTYPES:
        assert subtype.as_dict()["label"] == subtype.label, subtype.key
        assert f'"{subtype.label}":' not in dictionary, subtype.key
    for word, key in (
        ("Fonctionnalité", "feature"), ("Amélioration", "improvement"), ("Maintenance", "chore"),
        ("Performance", "perf"), ("Sécurité", "security"),
    ):
        assert subtypes.of(word) == key, word
    ideas = (FRONTEND / "src/components/console/idea-cards.tsx").read_text(encoding="utf-8")
    assert 'technical: "Tech"' in ideas and 't("Technical")' not in ideas


@case
def the_commit_the_pull_request_and_the_changelog_follow_the_sub_type():
    for key, commit, section in (
        ("bug", "fix", "Fixed"), ("feature", "feat", "Added"), ("improvement", "feat", "Changed"),
        ("chore", "chore", ""), ("refactor", "refactor", "Changed"), ("perf", "perf", "Changed"),
        ("docs", "docs", ""), ("security", "fix", "Security"),
    ):
        said = subtypes.section(key)
        assert f"starts with `{commit}: `" in said, key
        assert (f"under **{section}**" in said) if section else ("no entry" in said), key
    assert "reproduces the bug" in subtypes.section("bug")
    assert "reproduces" not in subtypes.section("feature")
    assert subtypes.section("") == ""

    assert subtypes.titled("feature", "Ponos — [Feature] Un badge") == "feat: Ponos — Un badge"
    assert subtypes.titled("bug", "[UX] [Bug] Le bouton") == "fix: [UX] Le bouton"
    assert subtypes.titled("docs", "Le README") == "docs: Le README"
    assert subtypes.titled("bug", "fix: déjà dit") == "fix: déjà dit"
    assert subtypes.titled("", "[Bug] x") == "[Bug] x"

    common = dict(project="p", title="T", body="b", repo="/r", branch="b", base="main", url="u")
    built = prompt.build(prompt.DEFAULT, **common, kind=subtypes.section("bug"))
    assert built.index("`fix: `") < built.index("# What is expected")
    assert "- Notion ticket: u\n\n# What is expected" in prompt.build(prompt.DEFAULT, **common)


@case
def the_sub_type_moves_the_level_a_code_ticket_starts_at():
    grid = C.Runner(use_fable=True).model_grid()
    body = "Une phrase."
    assert models.choose("Le README", body, kind="code", code=True, grid=grid).level == "standard"
    docs = models.choose("Le README", body, kind="code", code=True, grid=grid, subtype="docs")
    assert docs.level == "light" and ("model-subtype-lower", {"subtype": "docs"}) in docs.signals
    hole = models.choose("Le token", body, kind="code", code=True, grid=grid, subtype="security")
    assert hole.level == "heavy"
    writing = models.choose("Le token", body, kind="writing", code=False, grid=grid, subtype="security")
    assert writing.level == "light", "only a code ticket"
    path, _ = _saved()
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('\n[runner]\nauto_model_subtype_docs = "same"\nauto_model_subtype_bug = "nope"\n')
    loaded = C.load(path).runner
    assert loaded.subtype_shift("docs") == "same" and loaded.subtype_shift("bug") == "same"
    assert loaded.subtype_shift("security") == "higher"
    top = C.Runner(auto_model_code="heaviest").model_grid()
    assert models.choose("x", body, kind="code", code=True, grid=top, subtype="security").level == "heaviest"


@case
def init_offers_the_sub_type_column_and_doctor_names_it_when_it_is_missing():
    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    column = provision.tickets_schema(settings)["Sous-type"]
    options = [option["name"] for option in column["select"]["options"]]
    assert options == ["Bug", "Feature", "Amélioration", "Chore", "Refactor", "Perf", "Docs", "Sécurité"]
    assert files.schemas(settings)["tickets"]["Sous-type"] == "select"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        from ponos.__main__ import _doctor_columns
        _doctor_columns({"Status": "status"}, settings)
    assert "“Sous-type” missing" in out.getvalue(), out.getvalue()


@case
def the_backfill_fills_the_code_tickets_from_their_prefix_alone():
    def page(identifier: str, title: str, kind: str, subtype: str = "") -> notion.Page:
        properties = {"Type": {"type": "select", "select": {"name": kind}}}
        if subtype:
            properties["Sous-type"] = {"type": "select", "select": {"name": subtype}}
        return notion.Page(id=identifier, url="", title=title, properties=properties)

    done = page("f", "[Bug] Fermé depuis un an", "Code")
    done.properties["Status"] = {"type": "status", "status": {"name": "Done"}}
    pages = [
        done,
        page("a", "[Bug] Le bouton", "Code"),
        page("b", "[Docs] Le README", "Code", "Feature"),
        page("c", "Sans préfixe", "Code"),
        page("d", "[Bug] Un texte", "Rédaction"),
        page("e", "Ponos — [Ops] Node 24", "Code"),
    ]

    class Board(_SubtypedClient):
        def query(self, database_id, filter_=None):
            return pages

        def update(self, database_id, page_id, values):
            self.written.append({"id": page_id, **values})

    runner, _ = _nameless("x", "")
    runner.client = Board("")
    with _state_home(), _naming_session("{}") as asked:
        dry = runner.backfill_subtypes(write=False)
        assert [(one.id, key) for one, key in dry] == [("a", "bug"), ("e", "chore")]
        assert runner.client.written == []
        runner.backfill_subtypes()
    assert asked == [], "never a session"
    assert runner.client.written == [
        {"id": "a", "Sous-type": "Bug"}, {"id": "e", "Sous-type": "Chore"},
    ], runner.client.written
    assert [one.id for one, _ in runner.backfill_subtypes(write=False, closed=True)] == ["f", "a", "e"], (
        "a done ticket only when asked: an edit moves its closing date"
    )
    settings = C.Notion()
    assert web_api._subtype(done, settings) == "bug", "the console reads the prefix it was not given"
    assert web_api._subtype(pages[2], settings) == "feature", "the column wins"
    assert web_api._subtype(pages[4], settings) == "", "never on another type"


@case
def the_statistics_count_the_closed_tickets_by_sub_type_and_by_week():
    from ponos.web import statistics as web_statistics

    def card(identifier, subtype, edited, duration=None):
        return {"id": identifier, "column": "done", "subtype": subtype, "created": "2026-10-01",
                "edited": edited, "duration": duration}

    tickets = [
        card("a", "bug", "2026-10-06"), card("b", "bug", "2026-10-13", 30),
        card("c", "docs", "2026-10-13"), card("d", "", "2026-10-13"),
    ]
    history = [
        {"id": "a", "at": "2026-10-06T09:00:00+00:00", "cost_usd": 1.0, "seconds": 600},
        {"id": "b", "at": "2026-10-13T09:00:00+00:00", "cost_usd": 3.0},
    ]
    found = web_statistics.figures(tickets, history, date(2026, 10, 1), date(2026, 10, 20), timezone.utc)[
        "subtypes"
    ]
    assert found["total"] == 3, found
    assert found["weeks"][1]["counts"] == {"bug": 1} and found["weeks"][2]["counts"] == {"bug": 1, "docs": 1}
    bug = next(item for item in found["subtypes"] if item["key"] == "bug")
    assert (bug["count"], bug["cost"], bug["duration"]) == (2, 2.0, 20.0), bug
    docs = next(item for item in found["subtypes"] if item["key"] == "docs")
    assert docs["cost"] is None and docs["duration"] is None and docs["label"] == "Docs"
    # The console tells a sub-type by its colour alone: no emoji reaches it.
    assert "icon" not in docs, docs


# -- the model of a ticket ----------------------------------------------------


# Fable allowed, so the four levels are four models; see the use_fable cases.
_GRID = C.Runner(use_fable=True).model_grid()


def _chosen(title: str, body: str = "", **given) -> models.Choice:
    given.setdefault("kind", "code")
    given.setdefault("code", True)
    return models.choose(title, body, grid=given.pop("grid", _GRID), **given)


@case
def a_small_change_runs_on_the_light_model_and_says_why():
    choice = _chosen("Retirer un paragraphe des Réglages", "Le texte sous le titre ne sert à rien.")
    assert (choice.model, choice.level) == ("haiku", "light"), choice
    assert ("model-small", {"words": "retirer"}) in choice.signals, choice.signals
    said = voice.Voice("fr")
    reason = ", ".join(said.say(key, **values) for key, values in choice.signals)
    assert reason == "ticket code, petite modification ciblée (retirer)", reason
    # As tickets are really written: the context, what to do, the criteria.
    explained = "\n".join(
        [" ".join(["La page affiche un paragraphe que plus personne ne lit."] * 18)]
        + [f"- critère {number} vérifié sur desktop et mobile" for number in range(6)]
    )
    real = _chosen("Réglages : retirer le paragraphe d'explication", explained, priority=25)
    assert real.model == "haiku", "a small change said in its title, however explained"
    drowned = _chosen("Retirer la phrase et animer le robot", " ".join(["mot"] * 400))
    assert drowned.model == "sonnet", "past a page, the title alone does not make it small"
    writing = _chosen("Une phrase d'accroche", "Pour la page d'accueil.", kind="writing", code=False)
    assert writing.model == "haiku", "a short text is light from the start"


@case
def a_standard_bug_or_feature_runs_on_the_standard_model():
    body = " ".join(["Le formulaire de connexion renvoie une erreur quand l'email a une majuscule."] * 12)
    choice = _chosen("Connexion impossible avec une majuscule", body)
    assert (choice.model, choice.level) == ("sonnet", "standard"), choice
    assert choice.signals[-1] == ("model-ordinary", {})
    short = _chosen("Ajouter un bouton d'export CSV")
    assert short.model == "sonnet", "short, and nothing small about it: the type's level"


@case
def heavy_work_runs_on_a_heavy_model_and_the_heaviest_when_it_is_long_too():
    audit = _chosen("Audit de sécurité complet", "Passer tout le dépôt en revue.")
    assert (audit.model, audit.level) == ("opus", "heavy"), audit
    assert audit.signals[1] == ("model-heavy", {"words": "audit, sécurité"}), audit.signals
    steps = "\n".join(f"- point {number} à vérifier" for number in range(30))
    full = _chosen("Audit complet et migration de l'architecture", steps)
    assert (full.model, full.level) == ("fable", "heaviest"), full
    long = _chosen("Nouvelle page Statistiques", steps)
    assert long.model == "opus" and long.signals[1][0] == "model-long", long
    words = _chosen("Refonte", "Retirer le vieux texte.")
    assert words.model == "opus", "a heavy word wins over a small one"


@case
def an_action_on_the_world_or_an_urgent_ticket_never_runs_on_the_lightest_model():
    post = _chosen("Retirer le post LinkedIn", "", kind="publication", code=False)
    assert post.model == "sonnet", post
    urgent = _chosen("Renommer le bouton", "", priority=75)
    assert urgent.model == "sonnet" and urgent.signals[-1][0] == "model-urgent", urgent
    assert _chosen("Renommer le bouton", "", priority=74).model == "haiku"


@case
def a_priority_is_a_score_from_0_to_100_and_the_old_words_still_read():
    """Urgent, High, Normal, Low read as the scores their migration gives them,
    so a board not migrated yet keeps its order; what a cell says outside 0–100
    is clamped, what somebody gives is refused."""
    assert [priority.score(word) for word in ("Urgent", "high", "Normal", "Low")] == [100, 75, 50, 25]
    assert priority.score(None) == priority.score("") == 50, "empty is the middle"
    assert priority.score(150) == 100 and priority.score(-3) == 0 and priority.score(62.6) == 63
    assert priority.score("80") == 80 and priority.score("nonsense") == 50
    assert priority.given("") == 50 and priority.given(0) == 0 and priority.given("100") == 100
    for wrong in (101, -1, "vite", True):
        try:
            priority.given(wrong)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{wrong!r} is not a priority")
    assert [priority.word(score) for score in (100, 90, 75, 60, 50, 30, 0)] == [
        "Urgent", "Urgent", "High", "Normal", "Normal", "Low", "Low",
    ]
    assert priority.cell(80, "select") == "High" and priority.cell(80, "number") == 80


@case
def the_ready_tickets_run_by_score_highest_first_and_the_oldest_on_a_tie():
    def ready(identifier: str, created: str, cell: dict | None) -> notion.Page:
        properties = {"Priority": cell} if cell else {}
        return notion.Page(id=identifier, url="", title=identifier, properties=properties,
                           raw={"created_time": created})

    pages = [
        ready("plain", "2026-10-01T09:00:00Z", None),
        ready("low", "2026-09-01T09:00:00Z", {"type": "number", "number": 10}),
        ready("tienew", "2026-10-02T09:00:00Z", {"type": "number", "number": 90}),
        ready("tieold", "2026-09-02T09:00:00Z", {"type": "number", "number": 90}),
        ready("worded", "2026-09-03T09:00:00Z", {"type": "select", "select": {"name": "High"}}),
        ready("middle", "2026-09-04T09:00:00Z", {"type": "number", "number": 60}),
    ]
    runner = Runner.__new__(Runner)
    runner.config = _config("")
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    runner.client = type("S", (), {"query": lambda self, database, query=None: pages})()
    runner._ready_filter = lambda: {}
    runner.woken = lambda: []
    runner.parked = lambda tickets: set()
    eligible, waiting = runner.queue()
    assert [ticket.id for ticket in eligible] == [
        "tieold", "tienew", "worded", "middle", "plain", "low",
    ], [ticket.id for ticket in eligible]
    assert waiting == []


@case
def a_failed_choice_climbs_one_level_once_and_stays_there():
    earlier = models.Earlier("haiku", "failed")
    again = _chosen("Retirer le bandeau", earlier=earlier)
    assert (again.model, again.escalated) == ("sonnet", True), again
    assert again.signals[-1] == ("model-escalated", {"model": "haiku"})
    once = _chosen("Retirer le bandeau", earlier=models.Earlier("sonnet", "failed", escalated=True))
    assert (once.model, once.escalated) == ("sonnet", True), "climbed once, it stays there"
    assert once.signals == (("model-kept", {"model": "sonnet"}),)
    done = _chosen("Retirer le bandeau", earlier=models.Earlier("haiku", "done"))
    assert done.model == "haiku" and not done.escalated, "only a failure climbs"
    resumed = _chosen("Audit complet", earlier=models.Earlier("sonnet", "waiting"))
    assert resumed.model == "sonnet", "a session carried on keeps its model"
    off = _chosen("Retirer le bandeau", earlier=earlier, escalate=False)
    assert off.model == "haiku" and not off.escalated
    top = _chosen("Audit complet", earlier=models.Earlier("opus", "failed"))
    assert top.model == "fable" and top.escalated


@case
def the_grid_is_the_configurations_and_an_empty_level_borrows_the_nearest():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntoken = "x"\n[runner]\nauto_model_light = ""\n'
        'auto_model_heavy = "anthropic/claude-opus"\nauto_model_writing = "heavy"\n'
        'auto_model_code = "massive"\n',
        encoding="utf-8",
    )
    settings = C.load(path).runner
    grid = settings.model_grid()
    assert grid.model("light") == "sonnet", "below is nothing, so the one above"
    assert grid.model("heavy") == "anthropic/claude-opus"
    assert settings.auto_model_code == "standard", "a level nothing answers is the default"
    text = models.choose("Un mot", "", kind="writing", code=False, grid=grid)
    assert text.model == "anthropic/claude-opus", text


@case
def without_use_fable_the_heaviest_level_and_an_escalation_stop_at_opus():
    steps = "\n".join(f"- point {number} à vérifier" for number in range(30))
    heavy = "Audit complet et migration de l'architecture"
    assert C.Runner().use_fable is False, "Fable is a choice somebody makes"
    allowed = _chosen(heavy, steps, grid=C.Runner(use_fable=True).model_grid())
    assert (allowed.model, allowed.level) == ("fable", "heaviest"), allowed
    off = C.Runner().model_grid()
    refused = _chosen(heavy, steps, grid=off)
    assert (refused.model, refused.level) == ("opus", "heaviest"), refused
    named = C.Runner(auto_model_standard="claude-fable-5-1").model_grid()
    assert named.model("standard") == "opus", "any level named after Fable"
    top = _chosen("Audit complet", grid=off, earlier=models.Earlier("opus", "failed"))
    assert (top.model, top.escalated) == ("opus", False), top
    assert all(key != "model-escalated" for key, _ in top.signals)


@case
def a_config_without_use_fable_has_no_fable_and_true_brings_it_back():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "x"\n[runner]\n', encoding="utf-8")
    settings = C.load(path).runner
    assert settings.use_fable is False
    assert settings.auto_model_heaviest == "fable", "the level keeps its name"
    assert settings.model_grid().model("heaviest") == "opus"
    assert settings.allowed("fable") == "opus" and settings.allowed("sonnet") == "sonnet"
    path.write_text('[notion]\ntoken = "x"\n[runner]\nuse_fable = true\n', encoding="utf-8")
    settings = C.load(path).runner
    assert settings.use_fable is True and settings.allowed("fable") == "fable"


def _modelled(title: str, body: str, **properties):
    runner, ticket = _nameless(title, body)
    runner.client.said = []
    runner.client.comment = lambda page_id, text, discussion_id="": runner.client.said.append(text)
    ticket.page.properties.update(properties)
    return runner, ticket


@case
def a_ticket_with_no_model_is_given_one_and_told_why_in_a_comment():
    runner, ticket = _modelled("Retirer un paragraphe des Réglages", "Le texte sous le titre.")
    runner.config.runner.language = "fr"
    with _state_home():
        job = runner.prepare(ticket)
    assert (job.model, job.chosen, job.escalated) == ("haiku", True, False), job
    assert runner.client.said == [
        "🧠 Modèle choisi automatiquement — haiku\n"
        "Ticket Code, petite modification ciblée (retirer)."
    ], runner.client.said
    assert [values["Model"] for values in runner.client.written if "Model" in values] == [
        "haiku"
    ], "the pick is written on the ticket, with the value the comment announces"


@contextlib.contextmanager
def _failed_pick(model: str):
    """The journal remembering a run the runner chose `model` for, and lost."""
    original = journal.chosen
    journal.chosen = lambda ticket: {"model": model, "status": "failed", "escalated": False}
    try:
        yield
    finally:
        journal.chosen = original


@case
def a_model_written_by_the_runner_is_not_taken_for_one_somebody_chose():
    """The column holds the runner's pick on the next attempt: it must still
    be chosen for, or a run that failed could never climb. Another model there
    is somebody's, and is left alone."""
    column = lambda name: {"Model": {"type": "select", "select": {"name": name}}}
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.", **column("haiku"))
    with _state_home(), _failed_pick("haiku"):
        job = runner.prepare(ticket)
    assert job.chosen and job.model == "sonnet", (job.model, job.chosen)
    assert [values["Model"] for values in runner.client.written if "Model" in values] == [
        "sonnet"
    ]

    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.", **column("opus"))
    with _state_home(), _failed_pick("haiku"):
        job = runner.prepare(ticket)
    assert (job.model, job.chosen) == ("opus", False)
    assert not any("Model" in values for values in runner.client.written)


@case
def a_model_the_board_refuses_is_a_line_in_the_log_and_the_run_goes_on():
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    lines: list[str] = []
    runner.say = lines.append
    update = runner.client.update

    def refuse(database, page, values):
        if "Model" in values:
            raise store.StoreError("Model is expected to be rich_text")
        update(database, page, values)

    runner.client.update = refuse
    with _state_home():
        job = runner.prepare(ticket)
    assert (job.model, job.chosen) == ("haiku", True)
    assert any("model could not be written" in line for line in lines), lines


@case
def a_model_somebody_chose_or_a_switched_off_choice_is_the_runner_as_before():
    forced = {"Model": {"type": "select", "select": {"name": "opus"}}}
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.", **forced)
    with _state_home():
        job = runner.prepare(ticket)
    assert (job.model, job.chosen) == ("opus", False) and runner.client.said == []

    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    runner.config.runner.auto_model = False
    with _state_home():
        job = runner.prepare(ticket)
    assert (job.model, job.chosen) == ("", False) and runner.client.said == [], (
        "empty: runner.model, as every ticket had it"
    )


@case
def doctor_says_whether_fable_is_allowed():
    from ponos.__main__ import _doctor_fable

    for allowed, expected in ((False, "Claude Fable is not allowed: opus"), (True, "Fable allowed")):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _doctor_fable(C.Runner(use_fable=allowed))
        assert expected in out.getvalue(), out.getvalue()


@case
def a_fable_written_on_a_ticket_runs_on_opus_and_its_report_says_why():
    fable = {"Model": {"type": "select", "select": {"name": "fable"}}}
    runner, ticket = _modelled("Audit complet", "Tout le dépôt.", **fable)
    runner.config.runner.language = "fr"
    with _state_home():
        job = runner.prepare(ticket)
    assert (job.model, job.chosen) == ("opus", False), job
    assert job.notes == ["Fable désactivé dans les réglages : lancé sur Opus."], job.notes

    runner, ticket = _modelled("Audit complet", "Tout le dépôt.", **fable)
    runner.config.runner.use_fable = True
    with _state_home():
        job = runner.prepare(ticket)
    assert (job.model, job.notes) == ("fable", []), "allowed, taken as written"


@case
def a_run_begun_on_fable_carries_on_on_opus_once_it_is_turned_off():
    with _state_home():
        runner, ticket = _modelled("Audit complet", "Tout le dépôt.")
        journal.Run.start(ticket=ticket.id, model="fable", chosen=True, escalated=True).end("failed")
        job = runner.prepare(ticket)
        assert job.model == "opus", job
        runner, ticket = _modelled("Audit complet", "Tout le dépôt.")
        journal.Run.start(ticket=ticket.id, model="fable", chosen=True).end("waiting")
        assert runner.prepare(ticket).model == "opus"


@case
def a_chosen_model_that_failed_comes_back_one_level_up_from_the_journal():
    with _state_home():
        runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
        first = runner.prepare(ticket)
        journal.Run.start(ticket=ticket.id, model=first.model, chosen=True).end("failed")
        runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
        second = runner.prepare(ticket)
        assert (second.model, second.escalated) == ("sonnet", True), second
        assert "one level up after a failed run on haiku" in runner.client.said[-1]
        journal.Run.start(ticket=ticket.id, model=second.model, chosen=True, escalated=True).end("failed")
        runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
        third = runner.prepare(ticket)
        assert third.model == "sonnet", "once, not to the top of the price list"
        assert journal.chosen(ticket.id) == {"model": "sonnet", "status": "failed", "escalated": True}


@case
def a_title_is_one_line_however_the_session_wrapped_it():
    assert (
        naming.clean('Voici le titre :\n\n"Réparer le bandeau blanc"')
        == "Réparer le bandeau blanc"
    )
    assert naming.clean("**Retirer le shader du bandeau.**") == "Retirer le shader du bandeau"
    assert naming.clean("   ") == ""
    assert len(naming.clean("mot " * 40)) <= naming.LIMIT + 1, "a title is a line"
    assert "language the content is written in" in naming.prompt("Le bandeau reste blanc.")


@case
def a_fallback_title_is_the_first_line_that_says_something():
    body = "# Ce qu'il faut faire\n\n---\n- Retirer le shader.\nEt aussi le reste."
    assert naming.fallback(body) == "Retirer le shader"
    assert naming.fallback("## Titre\n## Autre\n") == "", "a bare template names nothing"
    assert naming.fallback("") == ""


# -- the live report ---------------------------------------------------------


def _assistant(*blocks) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool(name: str, **payload) -> dict:
    return {"type": "tool_use", "name": name, "input": payload}


@case
def an_event_becomes_the_line_a_human_would_write():
    steps = progress.describe(
        _assistant(
            {"type": "text", "text": "I will read the config.\n\nThen the tests."},
            _tool("Bash", command="npm test -- --watch=false"),
            _tool("Read", file_path="src/app/config.ts"),
        )
    )
    assert [step.line for step in steps] == [
        # What was said keeps its own shape; what was done is a line.
        "I will read the config.\nThen the tests.",
        "Bash · npm test -- --watch=false",
        "Read · src/app/config.ts",
    ]
    assert [step.said for step in steps] == [True, False, False]


@case
def what_the_agent_said_is_written_whole_and_not_cut_to_a_bullet():
    """A paragraph of reasoning is the part a human reads; it goes down entire."""
    said = "Le ticket parle de la documentation. " * 20  # far past a bullet's 200
    steps = progress.describe(_assistant({"type": "text", "text": said}))
    assert steps[0].label == said.strip() and "…" not in steps[0].label

    live, client, clock = _reporting()
    live.add(steps[0])
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 11
    live.flush()
    # Prose is a paragraph; a tool call never reaches the page.
    assert client.kinds == ["paragraph"]
    assert client.blocks[0] == said.strip()

    live.add(steps[0])
    clock.now += 11
    live.flush()
    # One paragraph after the other, no rule between them.
    assert client.kinds == ["paragraph", "paragraph"]
    # The board column shows a line, whatever the page shows.
    assert len(client.properties[-1]) <= progress.LINE


@case
def the_ticket_gets_what_the_agent_said_and_not_each_command():
    """“Bash · npx vite --port 5199” teaches nothing to whoever reads a ticket.

    The calls stay counted in the title and shown in the board's column; their
    detail is the log's and the console's. A failed one stays off as well: what
    the agent says next is what it made of it.
    """
    live, client, clock = _reporting()
    for step in progress.describe(
        _assistant(
            {"type": "text", "text": "Le port 5199 est pris ; je prends un autre port."},
            _tool("Bash", command="npx vite --port 5200"),
            _tool("Read", file_path="/tmp/portrait.png"),
            _tool("Edit", file_path="src/style.css"),
        )
    ) + progress.describe(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "is_error": True, "content": "exit 1"}]},
        }
    ):
        live.add(step)
    clock.now += 11
    live.flush()
    assert client.blocks == ["Le port 5199 est pris ; je prends un autre port."]
    assert client.titles[-1].startswith("⏳ Live — 5 steps")
    assert client.properties[-1] == "Error · exit 1"


@case
def a_turn_too_long_for_a_ticket_page_is_the_only_one_cut():
    steps = progress.describe(_assistant({"type": "text", "text": "x" * (progress.SAID + 500)}))
    assert len(steps[0].label) == progress.SAID and steps[0].label.endswith("…")

    live, client, clock = _reporting()
    live.add(steps[0])
    clock.now += 11
    live.flush()
    # Notion caps a piece of rich text, not a block: the paragraph is in pieces.
    assert client.pieces[-1] > 1 and client.blocks[-1] == steps[0].label


@case
def the_markdown_an_agent_writes_reaches_the_page_as_markup():
    live, client, clock = _reporting()
    live.add(progress.Step("**Interprétation** : lire `README.md`.", said=True))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Interprétation : lire README.md."], "no stray asterisks"
    marked = [name for mark in client.marks for name, on in mark.items() if on]
    assert marked == ["bold", "code"]


@case
def a_tool_nobody_named_still_says_what_it_touched():
    """An MCP tool, a new built-in: unknown is not a reason to say nothing."""
    steps = progress.describe(_assistant(_tool("mcp__github__create_pull_request", url="x/y#3")))
    assert steps[0].line == "create_pull_request · x/y#3"


@case
def only_a_failing_tool_result_is_worth_a_line():
    quiet = progress.describe(
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
    )
    loud = progress.describe(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "is_error": True, "content": [{"text": "exit 1"}]}
                ]
            },
        }
    )
    assert quiet == []
    assert loud[0].line == "Error · exit 1"
    # The payload is the log's business, never the ticket's.
    assert progress.describe({"type": "result", "num_turns": 4}) == []


class _Live:
    """A Notion that counts what a live report would have written to it."""

    def __init__(self, refuse=False):
        self.refuse = refuse
        self.blocks = []          # the text of every child appended under the toggle
        self.kinds = []           # and its block type
        self.pieces = []          # and how many pieces of rich text it took
        self.marks = []           # every annotation any of those pieces carried
        self.titles = []          # every title the toggle has carried
        self.properties = []      # every value written to the board column

    def append_blocks(self, block_id, blocks):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        if block_id == "page":
            return ["toggle"]
        for block in blocks:
            kind = block["type"]
            parts = block[kind].get("rich_text", [])
            self.kinds.append(kind)
            self.pieces.append(len(parts))
            self.blocks.append("".join(part["text"]["content"] for part in parts))
            self.marks += [part["annotations"] for part in parts if part.get("annotations")]
        return ["block"] * len(blocks)

    def update_block(self, block_id, payload):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.titles.append(payload["toggle"]["rich_text"][0]["text"]["content"])

    def update(self, database_id, page_id, values):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.properties.append(values["Progress"])


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _reporting(refuse=False, interval=10.0):
    clock, client = _Clock(), _Live(refuse)
    live = progress.Live(
        client,
        "page",
        database="db",
        property_name="Progress",
        interval=interval,
        clock=clock,
        say=lambda message: None,
    )
    return live, client, clock


@case
def the_steps_are_written_on_the_cadence_and_not_before():
    """Six events a second must not become six writes a second."""
    live, client, clock = _reporting()
    for index in range(5):
        clock.now += 1
        live.add(progress.Step("Read", f"file-{index}.py"))
    assert client.blocks == [], "nothing written before the cadence came round"

    assert client.titles == [], "nothing written before the cadence came round"

    clock.now += 6
    live.add(progress.Step("Bash", "pytest"))
    assert client.titles[-1].startswith("⏳ Live — 6 steps"), "one write, counting all that waited"
    assert client.properties[-1] == "Bash · pytest", "the board column shows the last step"


@case
def what_is_still_waiting_is_written_when_the_session_ends():
    live, client, clock = _reporting()
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close("removed the header")

    assert client.blocks == []
    assert client.titles[-1] == "✓ 1 step · 2 minutes · removed the header"
    # A finished ticket no longer claims to be doing anything.
    assert client.properties[-1] == ""


@case
def a_run_that_went_wrong_calls_its_block_a_trace_and_keeps_it_there():
    """The report is two lines and says where the rest is; the rest is here.

    Which is the whole move: what every comment used to end on — the command
    that resumes the session, the log, the worktree that was kept — is worth
    exactly one click on the day a run failed, and nothing at all on every
    other day.
    """
    live, client, clock = _reporting()
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close("it asked a question", ok=False)
    assert client.titles[-1] == "⚠️ Trace — 1 step · 2 minutes · it asked a question"

    assert live.detail("To pick the session back up: `claude --resume s-1`.")
    assert client.blocks[-1].startswith("To pick the session back up")
    assert not live.detail("  "), "nothing to file is not something to file"


@case
def a_ticket_with_no_block_to_file_a_trace_in_keeps_it_in_the_report():
    """A trace nobody can find is a trace nobody has."""
    live, client, _ = _reporting()
    assert not live.detail("`claude --resume s-1`"), "no step, no toggle, nowhere to put it"
    assert client.blocks == []


@case
def the_block_a_run_leaves_speaks_the_language_the_report_does():
    """“⏳ Live — 16 step(s)” under a French verdict is one glance, two languages."""
    clock, client = _Clock(), _Live()
    live = progress.Live(client, "page", words=voice.Voice("fr"), clock=clock)
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close()
    assert client.titles[0].startswith("⏳ En cours")
    assert client.titles[-1] == "✓ 1 étape · 2 minutes"


class _Page:
    """A Notion page as a tree of blocks: written by a live report, read by the client."""

    def __init__(self):
        self.children: dict[str, list[dict]] = {"page": []}
        self.asked: list[str] = []

    def add(self, parent: str, block: dict) -> str:
        identifier = uuid.uuid4().hex
        kind = block["type"]
        rich = [
            {**part, "plain_text": part["text"]["content"]} for part in block[kind]["rich_text"]
        ]
        self.children[parent].append(
            {"id": identifier, "has_children": False, **block, kind: {"rich_text": rich}}
        )
        self.children[identifier] = []
        for held in self.children.values():
            for child in held:
                child["has_children"] = bool(self.children.get(child["id"]))
        return identifier

    def append_blocks(self, block_id, blocks):
        return [self.add(block_id, block) for block in blocks]

    def update_block(self, block_id, payload):
        for held in self.children.values():
            for child in held:
                if child["id"] == block_id:
                    child["toggle"]["rich_text"] = [
                        {**part, "plain_text": part["text"]["content"]}
                        for part in payload["toggle"]["rich_text"]
                    ]

    def update(self, database_id, page_id, values):
        pass

    def request(self, method, path, body=None, **_):
        parent = path.split("/")[2]
        self.asked.append(parent)
        return {"results": self.children[parent], "has_more": False}


def _run_on(page, words: str, said: str, *, ok: bool = True, page_id: str = "page") -> None:
    """One session's live report, as `execution` would leave it on the page."""
    clock = _Clock()
    live = progress.Live(page, page_id, words=voice.Voice(words), clock=clock)
    live.add(progress.Step(said, said=True))
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 90
    live.close("stopped" if not ok else "", ok=ok)


@case
def a_brief_is_read_without_the_story_of_earlier_runs():
    """A ticket sent back to Ready is briefed on what you wrote, not on its past runs.

    Every run leaves its toggle on the page; read as a brief, the page skips
    them — and does not even ask Notion for what they hold. The report a run
    ends on, and a toggle somebody wrote by hand, are still read.
    """
    page = _Page()
    page.add("page", markdown.to_blocks("## À faire\n\nCorriger l'entête.")[0])
    page.add("page", markdown.to_blocks("Corriger l'entête.")[0])
    _run_on(page, "fr", "Je lis la configuration.", ok=False)
    page.add("page", markdown.to_blocks("Pull request ouverte : x/y#3")[0])
    _run_on(page, "en", "Reading the header again.")
    by_hand = page.add(
        "page",
        {"object": "block", "type": "toggle",
         "toggle": {"rich_text": [{"type": "text", "text": {"content": "Notes"}}]}},
    )
    page.add(by_hand, markdown.to_blocks("Garder le logo.")[0])
    titles = [
        "".join(part["plain_text"] for part in block["toggle"]["rich_text"])
        for block in page.children["page"] if block["type"] == "toggle"
    ]
    assert titles[0].startswith("⚠️ Trace — 2 étapes") and titles[1].startswith("✓ 2 steps"), titles
    runs = [block["id"] for block in page.children["page"] if progress.is_live(block)]
    assert len(runs) == 2

    client = notion.Client("ntn_x")
    client._request = page.request  # type: ignore[method-assign]
    brief = client.blocks_text("page", live=False)
    assert brief == (
        "## À faire\nCorriger l'entête.\nPull request ouverte : x/y#3\nNotes\n  Garder le logo."
    ), brief
    assert not set(runs) & set(page.asked), "a run's toggle is not even opened"
    whole = client.blocks_text("page")
    assert "Je lis la configuration." in whole and "Reading the header again." in whole
    assert "Trace" in whole


@case
def a_toggle_that_only_looks_like_a_run_is_kept():
    def toggle(title, bold=True):
        part = {"type": "text", "text": {"content": title}, "annotations": {"bold": bold}}
        return {"type": "toggle", "toggle": {"rich_text": [part]}}

    assert progress.is_live(toggle("⏳ Live"))
    assert progress.is_live(toggle("⏳ En cours — 4 étapes · moins d'une minute"))
    assert progress.is_live(toggle("✓ 16 step(s) · 3 min"))
    assert progress.is_live(toggle("⚠️ Trace — 3 steps · 2 minutes · interrupted"))
    assert not progress.is_live(toggle("✓ Done items"))
    assert not progress.is_live(toggle("⏳ Live", bold=False))
    assert not progress.is_live(toggle("Notes"))
    assert not progress.is_live({"type": "paragraph", "paragraph": toggle("⏳ Live")["toggle"]})


@case
def a_session_that_did_nothing_leaves_no_toggle_behind():
    live, client, _ = _reporting()
    live.close("nothing to do")
    assert client.blocks == [] and client.titles == []


@case
def the_same_step_twice_in_a_row_is_said_once():
    live, client, clock = _reporting()
    live.add(progress.Step("Je lis la config.", said=True))
    live.add(progress.Step("Je lis la config.", said=True))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/y.py"))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Je lis la config."]
    assert client.titles[-1].startswith("⏳ Live — 3 steps")


@case
def a_notion_that_refuses_costs_the_report_and_not_the_ticket():
    """Reporting is commentary: it never becomes a reason to fail a ticket."""
    live, client, clock = _reporting(refuse=True)
    for index in range(10):
        clock.now += 11
        live.add(progress.Step("Read", f"file-{index}.py"))
    live.close("done anyway")
    assert live.disabled and client.blocks == []


@case
def a_reporter_never_writes_more_than_a_page_can_hold():
    live, client, clock = _reporting()
    for index in range(progress.MAX_STEPS + 50):
        live.add(progress.Step(f"Paragraphe {index}.", said=True))
    clock.now += 11
    live.flush()
    assert len(client.blocks) == progress.MAX_STEPS + 1, "the prose, then one line saying enough"
    assert client.blocks[-1].startswith("…")

    # Capped is not disabled: the page stops, the title still counts and ends.
    live.add(progress.Step("Encore un.", said=True))
    clock.now += 11
    live.close("done")
    assert len(client.blocks) == progress.MAX_STEPS + 1
    assert client.titles[-1].startswith(f"✓ {progress.MAX_STEPS + 51} steps")
    assert client.titles[-1].endswith("· done")


@case
def tool_calls_by_the_hundred_do_not_cost_the_prose_its_place():
    live, client, clock = _reporting()
    for index in range(progress.MAX_STEPS + 50):
        live.add(progress.Step("Read", f"file-{index}.py"))
    live.add(progress.Step("Tout est lu ; je lance les tests.", said=True))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Tout est lu ; je lance les tests."]



# -- the web console ---------------------------------------------------------


@case
def a_typed_command_is_split_without_a_shell():
    """No shell means no metacharacter: the words go to execve as they are."""
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert commands.parse(">status") == ["status"]
    assert commands.parse("history -n 5") == ["history", "-n", "5"]
    # A quoted argument stays one argument, accents and spaces included.
    assert commands.parse('logs "à faire"') == ["logs", "à faire"]


@case
def a_command_the_cli_does_not_have_is_refused():
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    for line in ("rm -rf /", "run; rm -rf /", "sh -c whoami", "../../bin/sh"):
        try:
            commands.parse(line)
        except ValueError:
            continue
        raise AssertionError(f"{line!r} should not have been accepted")


@case
def the_commands_that_would_hang_a_browser_are_not_offered():
    """`config` opens an editor and `serve` is the console itself.

    Both are refused *and* left out of the list the error message offers: naming
    a verb and then refusing it is a small lie told to somebody already lost.
    """
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    for verb in web_console.REFUSED:
        assert verb not in commands.allowed
        try:
            commands.parse(verb)
        except ValueError as error:
            assert verb in str(error)
        else:
            raise AssertionError(f"{verb} should have been refused")
    assert "status" in commands.allowed


@case
def the_console_runs_what_it_lists_and_nothing_the_cli_grows_later():
    """A list written down, not the parser read back.

    Deriving the verbs from the parser made every new command something a
    browser could start. `run` starts Claude sessions that outlive the command's
    timeout, `update` swaps the code the console runs on, `clean` deletes the
    worktree a session is standing in: none of them is typed into a web page.
    """
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert set(commands.allowed) <= set(web_console.OFFERED)
    assert set(commands.allowed) <= set(subcommands()), "never a verb the CLI does not have"
    for verb in ("run", "update", "clean", "init", "enable"):
        assert verb not in commands.allowed, verb
        try:
            commands.parse(f"{verb} --force")
        except ValueError as error:
            assert verb in str(error), error
        else:
            raise AssertionError(f"{verb} should have been refused")
    grown = web_console.Commands(lambda *a, **k: None, (*subcommands(), "wipe"))
    assert "wipe" not in grown.allowed, "a verb added to the CLI is not offered by itself"


@case
def a_command_that_runs_too_long_takes_what_it_started_with_it():
    """The timeout ends the command's process group, not only its leader.

    `process.kill` used to stop the Python the console started and leave its
    children — a Claude session, from `run` — running unowned. The shell below
    starts a child of its own and waits on it; both have to be gone.
    """
    events: list[tuple[str, dict]] = []
    commands = web_console.Commands(lambda kind, **said: events.append((kind, said)), ())
    commands.timeout = 1
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "child"
        script = f"sleep 60 & echo $! > {marker}; echo started; wait"
        started = time.monotonic()
        commands._stream(["sh", "-c", script])
        took = time.monotonic() - started
        child = int(marker.read_text().strip())

    assert took < 30, f"the watchdog did not end the command ({took:.0f}s)"
    assert events[-1] == ("command", {"stage": "ended", "code": events[-1][1]["code"]})
    assert events[-1][1]["code"] != 0
    assert any("stopped after" in said.get("text", "") for _, said in events), events
    try:
        stat = Path(f"/proc/{child}/stat").read_text()
    except OSError:
        return  # gone entirely
    assert stat.split(")")[-1].split()[0] in ("Z", "X"), f"the child is still running: {stat}"


@case
def following_a_log_is_dropped_rather_than_left_to_hang():
    """`logs -f` never returns, and the live panel already is that feed."""
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert commands.parse("logs -f") == ["logs"]
    assert commands.parse("logs abc123 --follow") == ["logs", "abc123"]


# -- what a message to the workspace carries ----------------------------------


@contextmanager
def _chat(body: str = ""):
    """A Chat whose Claude session is a function, in a throwaway state directory."""
    with _state_home():
        prompts: list[str] = []
        events: list[tuple[str, dict]] = []
        original_run, original_available = session.run, session.available

        def run(prompt, **_):
            prompts.append(prompt)
            return session.Outcome(True, False, "sid", "", Path("/dev/null"), answer="seen")

        session.run = run
        session.available = lambda: "/usr/bin/claude"
        try:
            chat = web_console.Chat(_config(body), lambda kind, **said: events.append((kind, said)))
            chat.prompts = prompts  # type: ignore[attr-defined]
            chat.events = events  # type: ignore[attr-defined]
            yield chat
        finally:
            session.run, session.available = original_run, original_available


def _said_to(chat) -> str:
    """The prompt of the last turn, once its thread has answered."""
    for _ in range(200):
        if not chat.busy:
            break
        time.sleep(0.01)
    return chat.prompts[-1]


@case
def a_message_of_words_alone_reaches_the_session_as_it_was_typed():
    with _chat() as chat:
        chat.send("what is on the board?")
        prompt = _said_to(chat)
        assert prompt.endswith("what is on the board?")
        assert "Attached to this message" not in prompt
        assert chat.history()[0] == {**chat.history()[0], "role": "you", "text": "what is on the board?"}
        assert "attachments" not in chat.history()[0], "no files, no empty list"


@case
def an_image_travels_as_a_path_the_session_reads():
    """Claude Code takes no file in a request: it reads one from the disk."""
    with _chat() as chat:
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        said = chat.attach("capture d'écran.png", io.BytesIO(png), len(png))
        assert said["kind"] == "image" and said["type"] == "image/png" and said["size"] == len(png)
        kept = chat.attachment(said["id"]).path
        assert kept.read_bytes() == png
        assert kept.is_relative_to(web_console.attachments_dir()), "under the state, never a repository"
        chat.send("what is wrong on this screen?", [said["id"]])
        prompt = _said_to(chat)
        assert str(kept) in prompt, "the absolute path is what the session is given"
        assert "Read tool" in prompt
        assert chat.history()[0]["attachments"][0]["id"] == said["id"]
        sent = [said for kind, said in chat.events if said.get("stage") == "sent"][0]
        assert sent["attachments"][0]["name"] == said["name"], "the other tab draws it too"


@case
def a_document_goes_with_or_without_words():
    with _chat() as chat:
        pdf = b"%PDF-1.7\n" + b"0" * 50
        said = chat.attach("spec.pdf", io.BytesIO(pdf), len(pdf))
        sheet = chat.attach("../../etc/budget.xlsx", io.BytesIO(b"PK" * 10), 20)
        assert sheet["name"] == "budget.xlsx", "only the last component of a name is kept"
        chat.send("", [said["id"], sheet["id"]])
        prompt = _said_to(chat)
        assert "spec.pdf" in prompt and "A PDF" in prompt
        assert "budget.xlsx" in prompt and "Office file" in prompt


@case
def a_video_is_looked_at_through_frames_or_said_to_be_unseen():
    with _chat() as chat:
        said = chat.attach("clip.mp4", io.BytesIO(b"\x00" * 64), 64)
        video = chat.attachment(said["id"])
        original = web_attachments.ffmpeg
        web_attachments.ffmpeg = lambda: ""
        try:
            unseen = web_attachments.brief([video])
        finally:
            web_attachments.ffmpeg = original
        assert "ffmpeg is not installed" in unseen and "rather than guess" in unseen


@case
def a_file_past_the_limit_or_of_the_wrong_kind_is_refused_with_a_reason():
    with _chat("[web]\nattachment_max_mb = 1\n") as chat:
        heavy = 2 * 1024 * 1024
        try:
            chat.attach("film.mov", io.BytesIO(b""), heavy)
        except web_attachments.TooLarge as error:
            assert "web.attachment_max_mb" in str(error) and "2 MB" in str(error)
        else:
            raise AssertionError("a file past the limit was kept")
        for name in ("page.html", "logo.svg", "script"):
            try:
                chat.attach(name, io.BytesIO(b"<x>"), 3)
            except ValueError as error:
                assert "not a kind of file" in str(error)
            else:
                raise AssertionError(f"{name} was kept")
        try:
            chat.send("look", ["0123456789ab"])
        except LookupError:
            pass
        else:
            raise AssertionError("a message whose file is gone was sent without it")
        assert not chat.history(), "refused whole"


@case
def a_new_conversation_leaves_the_old_one_its_files_until_it_is_deleted():
    with _chat() as chat:
        chat.send("look at this")
        _said_to(chat)
        said = chat.attach("a.png", io.BytesIO(b"png"), 3)
        chat.send("and this one")
        _said_to(chat)
        old, folder = chat.id, chat.folder().path
        assert folder.is_dir()
        chat.reset()
        assert folder.is_dir(), "the old conversation is still in the list, with its files"
        try:
            chat.attachment(said["id"])
        except LookupError:
            pass
        else:
            raise AssertionError("the new conversation reads the old one's files")
        again = chat.attach("b.png", io.BytesIO(b"png"), 3)
        assert chat.folder().path != folder, "a new conversation, a new folder"
        assert chat.attachment(again["id"]).name == "b.png"
        chat.delete(old)
        assert not folder.exists(), "deleting a conversation takes its files with it"
        assert [item["id"] for item in chat.sessions()] == [], "the new one has said nothing yet"


@case
def conversations_are_listed_reopened_renamed_and_searched():
    with _chat() as chat:
        chat.send("How do I rotate the Notion token?\nSecond line")
        _said_to(chat)
        first = chat.id
        assert chat.title == "How do I rotate the Notion token?", chat.title
        chat.reset()
        assert chat.history() == [] and chat.session_id == ""
        chat.send("Draft the release notes")
        _said_to(chat)
        second = chat.id
        listed = chat.sessions()
        assert [item["id"] for item in listed] == [second, first], "the latest first"
        assert listed[0]["current"] and not listed[1]["current"]
        assert [item["id"] for item in chat.sessions("notion")] == [first]
        assert chat.sessions("notion")[0]["matched"] == "title"
        assert chat.sessions("seen")[0]["matched"] == "content", "the answers are searched too"
        assert chat.sessions("100%") == [], "a wildcard is a character"
        chat.rename(first, "  Token   rotation ")
        assert chat.sessions("rotation")[0]["title"] == "Token rotation"
        chat.link(first, " Website ")
        assert chat.sessions("website")[0]["project"] == "Website", "found by its project too"
        chat.open(first)
        assert chat.id == first and chat.history()[0]["text"].startswith("How do I rotate")
        chat.send("and then?")
        assert "and then?" in _said_to(chat), "the session is resumed, without the brief again"
        assert chat.prompts[-1].startswith("[This conversation is about the project “Website”.]")
        assert chat.session_id and chat.turns == 2
        try:
            chat.open("0123456789ab")
        except LookupError:
            pass
        else:
            raise AssertionError("opened a conversation that does not exist")
        chat.delete(first)
        assert [item["id"] for item in chat.sessions()] == [second]
        assert chat.history() == [], "the deleted one was open: a blank one takes its place"


@case
def a_conversation_keeps_its_model_and_the_settings_name_the_default():
    with _chat('[web]\nchat_model = "haiku"\n') as chat:
        assert chat.effective_model() == "haiku", "the setting is the default of a new session"
        chat.choose("opus")
        assert chat.state()["model"] == "opus"
        chat.send("hello")
        _said_to(chat)
        first = chat.id
        chat.reset()
        assert chat.effective_model() == "haiku", "a new session starts on the default again"
        chat.open(first)
        assert chat.effective_model() == "opus", "and the other one remembers its own"
        chat.choose("")
        assert chat.effective_model() == "haiku"
        for refused in ("openai/gpt-5", "--dangerous", "a b"):
            try:
                chat.choose(refused)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{refused} was accepted")
        offered = chat.models()
        assert [item["id"] for item in offered["claude"]] == ["opus", "sonnet", "haiku", "fable"]
        assert offered["openrouter"] == {"configured": False, "models": [], "error": ""}


@case
def an_openrouter_model_goes_through_openrouter_whatever_the_provider():
    body = '[openrouter]\nkey = "sk-or-test"\n'
    with _chat(body) as chat:
        seen: list[dict] = []
        original = session.run

        def run(prompt, **rest):
            seen.append(rest)
            return original(prompt, **rest)

        session.run = run
        chat.choose("deepseek/deepseek-r1")
        chat.send("hello")
        _said_to(chat)
        assert seen[-1]["model"] == "deepseek/deepseek-r1", "a slug is not rewritten"
        assert seen[-1]["environment"]["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"
        assert seen[-1]["environment"]["ANTHROPIC_BASE_URL"].startswith("https://openrouter.ai")
        chat.choose("sonnet")
        chat.send("again")
        _said_to(chat)
        assert seen[-1]["model"] == "sonnet"
        assert "ANTHROPIC_BASE_URL" not in seen[-1]["environment"], "a Claude model stays on the CLI"
        assert chat.models()["recent"] == ["sonnet"]


@case
def the_catalogue_of_openrouter_is_read_once_and_a_failure_is_said():
    import urllib.request
    from ponos import openrouter as router

    answers = [json.dumps({"data": [{"id": "a/b", "name": "A: B"}, {"name": "no id"}]}).encode()]
    opened: list[str] = []

    class Reply:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return self.body

    def urlopen(request, timeout=0):
        opened.append(request.full_url)
        return Reply(answers[0])

    original, router._catalogue = urllib.request.urlopen, {}
    urllib.request.urlopen = urlopen
    try:
        settings = _config('[openrouter]\nkey = "k"\n').openrouter
        assert router.catalogue(settings) == [{"id": "a/b", "name": "A: B"}]
        router.catalogue(settings)
        assert len(opened) == 1, "kept for a while"
        router._catalogue = {}
        answers[0] = b"nope"
        try:
            router.catalogue(settings)
        except router.Unavailable as error:
            assert "not JSON" in str(error)
        else:
            raise AssertionError("a page that is not JSON was read as a catalogue")
    finally:
        urllib.request.urlopen, router._catalogue = original, {}


@case
def the_single_conversation_of_chat_json_becomes_the_first_of_the_list():
    with _state_home():
        web_console.web_dir().joinpath("chat.json").write_text(
            json.dumps({
                "session_id": "abc", "turns": 1,
                "messages": [
                    {"role": "you", "text": "an old question", "at": "2026-01-01T10:00:00+00:00"},
                    {"role": "workspace", "text": "an old answer", "at": "2026-01-01T10:01:00+00:00"},
                ],
            }),
            encoding="utf-8",
        )
        chat = web_console.Chat(_config(""), lambda *a, **k: None)
        assert chat.title == "an old question" and chat.session_id == "abc"
        assert len(chat.history()) == 2
        assert not (web_console.web_dir() / "chat.json").exists(), "read once, then set aside"
        assert len(web_console.Chat(_config(""), lambda *a, **k: None).sessions()) == 1


@case
def a_stopped_session_takes_what_it_had_started_with_it():
    """Stop ends the CLI *and* the command it was running: nothing runs after it."""
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        ticks = home / "ticks"
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, subprocess, sys, time\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': ["
            "{'type': 'text', 'text': 'Looking.'}]}}), flush=True)\n"
            # A long command, the way a session runs one: a child that writes.
            f"subprocess.Popen(['/bin/sh', '-c', 'while true; do echo x >> {ticks}; sleep 0.05; done'])\n"
            "time.sleep(60)\n"
        )
        (home / "claude").chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        stop = threading.Event()
        try:
            def press() -> None:
                while not ticks.exists():
                    time.sleep(0.02)
                stop.set()

            threading.Thread(target=press, daemon=True).start()
            began = time.monotonic()
            outcome = session.run(
                "look", cwd=home, log=home / "stopped.jsonl", timeout_minutes=1, stop=stop
            )
        finally:
            os.environ["PATH"] = previous
        assert time.monotonic() - began < 10, "stopped, not timed out"
        assert outcome.stopped and not outcome.ok and not outcome.blocked
        assert outcome.answer == "Looking.", "what it had said is kept"
        size = ticks.stat().st_size
        time.sleep(0.3)
        assert ticks.stat().st_size == size, "the command it had started still runs"


def _halting(chat, exists: bool = True):
    """The `_chat` session, made to wait for Stop and say what it had done."""
    calls: list[dict] = []

    def run(prompt, **rest):
        calls.append(rest)
        chat.prompts.append(prompt)
        if rest["stop"].wait(5):
            return session.Outcome(
                False, False, rest["session_id"], "", Path("/dev/null"),
                answer="halfway", error="stopped", stopped=True,
            )
        return session.Outcome(True, False, rest["session_id"], "", Path("/dev/null"), answer="done")

    session.run = run
    session.exists = lambda identifier: exists
    return calls


def _settled(chat) -> None:
    for _ in range(300):
        if not chat.busy:
            return
        time.sleep(0.01)
    raise AssertionError("the turn never ended")


@case
def a_stopped_turn_is_kept_and_the_conversation_carries_on():
    original = session.exists
    try:
        with _chat() as chat:
            calls = _halting(chat)
            assert chat.stop()["busy"] is False, "nothing to stop is not an error"
            chat.send("rewrite everything")
            identifier = chat.session_id
            chat.stop()
            chat.stop()  # the double click
            _settled(chat)
            stages = [said["stage"] for kind, said in chat.events if kind == "chat"]
            assert stages.count("stopping") == 1, stages
            assert stages[-1] == "stopped"
            assert chat.history()[-1] == {**chat.history()[-1], "role": "stopped", "text": "halfway"}
            assert chat.session_id == identifier and chat.turns == 1
            chat.send("only the README, then")
            chat.stop()
            _settled(chat)
            assert calls[-1]["resume"] is True and calls[-1]["session_id"] == identifier
            # Read back from the disk, a stopped turn with nothing said stays.
            chat.messages.append(web_console.Message("stopped", ""))
            chat._save()
            again = web_console.Chat(chat.config, lambda *a, **k: None)
            assert [message.role for message in again.messages][-1] == "stopped"
    finally:
        session.exists = original


@case
def a_first_turn_stopped_before_it_was_filed_starts_afresh():
    original = session.exists
    try:
        with _chat() as chat:
            calls = _halting(chat, exists=False)
            chat.send("hello")
            chat.stop()
            _settled(chat)
            assert chat.session_id == "", "nothing to resume"
            chat.send("hello again")
            chat.stop()
            _settled(chat)
            assert calls[-1]["resume"] is False, "a fresh session, not a stranger resumed"
            assert chat.prompts[-1] != "hello again", "with the brief, as a first turn is"
    finally:
        session.exists = original


@case
def files_nobody_closed_the_conversation_on_go_after_their_days():
    with _state_home():
        root = web_console.attachments_dir()
        folder = web_attachments.Folder(root, "old")
        kept = folder.save("x.png", io.BytesIO(b"png"), 3, 100)
        fresh = folder.save("y.png", io.BytesIO(b"png"), 3, 100)
        old = time.time() - 9 * 86400
        os.utime(kept.path, (old, old))
        assert web_attachments.prune(root, 7) == 1
        assert not kept.path.exists() and fresh.path.exists()
        os.utime(fresh.path, (old, old))
        web_attachments.prune(root, 7)
        assert not folder.path.exists(), "an emptied folder goes too"


@case
def dictation_without_a_key_says_what_is_missing():
    with _chat() as chat:
        state = chat.state()["dictation"]
        assert state["ready"] is False and "OpenRouter key" in state["why"]
        try:
            chat.transcribe(b"audio", "audio/webm")
        except openrouter.Unavailable as error:
            assert "openrouter.key" in str(error)
        else:
            raise AssertionError("a transcription was attempted with no key")


@case
def dictation_is_sent_to_openrouter_in_the_language_asked_for():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received: list[dict] = []

    class Whisper(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):  # noqa: N802
            received.append({
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
            })
            answer = json.dumps({"text": " Bonjour la machine. "}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Whisper)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
        with _chat(f'[openrouter]\nkey = "sk-or-test"\nbase_url = "{base}"\n') as chat:
            assert chat.state()["dictation"]["ready"] is True
            said = chat.transcribe(b"\x1aE\xdf\xa3", "audio/webm;codecs=opus", "fr-FR")
    finally:
        server.shutdown()
        server.server_close()
    assert said == {"text": "Bonjour la machine.", "language": "fr"}
    request = received[0]
    assert request["path"] == "/api/v1/audio/transcriptions"
    assert request["auth"] == "Bearer sk-or-test"
    assert request["body"]["model"] == "openai/whisper-1"
    assert request["body"]["input_audio"]["format"] == "webm"
    assert request["body"]["language"] == "fr"
    assert openrouter.audio_format("audio/mp4") == "m4a"


@case
def the_console_takes_a_file_as_a_raw_body_and_serves_it_back_sandboxed():
    """Over HTTP, with the guard header and the size limit the page cannot skip."""
    import urllib.error
    import urllib.request

    from ponos.web import server as web_server

    with _chat("[web]\nattachment_max_mb = 1\n") as chat:
        api = _bare_api(_TalkClient([]))
        api.chat = chat
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"

        def post(path: str, body: bytes, guard: bool = True, kind: str = "image/png"):
            headers = {"Authorization": "Bearer tok", "Content-Type": kind}
            if guard:
                headers["X-Ponos"] = "1"
            request = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read()), response.headers
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read() or b"{}"), error.headers

        try:
            code, _, _ = post("/api/chat/attachments?name=a.png", b"png", guard=False)
            assert code == 403, "a page elsewhere cannot drop a file here"
            code, said, _ = post("/api/chat/attachments?name=a.png", b"\x89PNG")
            assert code == 200 and said["kind"] == "image", said
            code, refused, _ = post("/api/chat/attachments?name=big.png", b"x" * (1024 * 1024 + 1))
            assert code == 413 and "attachment_max_mb" in refused["error"], refused
            code, refused, _ = post("/api/chat/transcribe?lang=fr", b"audio", kind="audio/webm")
            assert code == 503 and "OpenRouter key" in refused["error"], refused

            request = urllib.request.Request(
                f"{base}/api/chat/attachments/{said['id']}", headers={"Authorization": "Bearer tok"}
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.read() == b"\x89PNG"
                assert response.headers["Content-Type"] == "image/png"
                assert "sandbox" in response.headers["Content-Security-Policy"]
            code, _, _ = post(f"/api/chat/attachments/{said['id']}/remove", b"{}", kind="application/json")
            assert code == 200
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                assert error.code == 404
            else:
                raise AssertionError("a removed file is still served")
        finally:
            console.shutdown()
            console.server_close()


@case
def the_message_bar_is_one_block_with_its_gestures_inside():
    """The bar is a component a ticket's thread can take, and the old form is gone.

    Read from the React source: what is checked is a decision about the page,
    which the bundle has minified away.
    """
    bar = (FRONTEND / "src/components/console/composer.tsx").read_text(encoding="utf-8")
    pane = (FRONTEND / "src/components/console/console-pane.tsx").read_text(encoding="utf-8")
    assert "export function Composer" in bar
    for gesture in ("PlusIcon", "MicIcon", "ArrowUpIcon", "onPaste", "rounded-full", "max-w-3xl"):
        assert gesture in bar, f"the bar lost {gesture}"
    assert "<Composer" in pane and "onDrop" in pane, "the drawer takes a dropped file"
    assert "<Textarea" not in pane, "the bare field is back"
    assert 't("Send")' not in pane, "a text button for sending is back under the field"
    assert "a sentence talks to your workspace ·" not in pane, "the permanent help line is back"
    tests = (FRONTEND / "src/lib/composer.test.ts").read_text(encoding="utf-8")
    for held in ("removed by its cross", "pasted screenshot", "starts with > is a command", "arrow is off"):
        assert held in tests, f"nothing holds the bar to “{held}” any more"
    accepted = set(re.findall(r"^  (\w+): \"(?:image|video|document)\"", (
        FRONTEND / "src/lib/composer.ts"
    ).read_text(encoding="utf-8"), re.M))
    assert accepted == set(web_attachments.ACCEPTED), "the page and the server accept different files"


@case
def a_browser_that_reconnects_is_given_only_what_it_missed():
    """The backlog is replayed by event id, or a suspend would double the chat."""
    hub = web_live.Hub()
    hub.publish("chat", stage="sent", text="one")
    hub.publish("chat", stage="answer", text="two")
    hub.publish("board", tickets=[])

    fresh = hub.subscribe()  # a first connection: the board, and no transcript
    kinds = [fresh.get_nowait().kind for _ in range(fresh.qsize())]
    assert kinds == ["board"], kinds

    back = hub.subscribe(after=1)  # a reconnection, having seen event 1
    seen = [back.get_nowait() for _ in range(back.qsize())]
    assert [event.kind for event in seen] == ["chat", "board"]
    assert seen[0].payload["text"] == "two"


@case
def an_event_carries_its_id_so_the_browser_can_ask_again():
    hub = web_live.Hub()
    hub.publish("step", label="Read", detail="src/x.py")
    channel = hub.subscribe(after=0)
    hub.publish("step", label="Bash", detail="npm test")
    event = channel.get_nowait()
    assert event.encode().startswith("id: 2\nevent: step\ndata: {")
    assert '"label": "Bash"' in event.encode()


@case
def a_log_line_becomes_the_step_the_board_would_have_shown():
    """The live panel and the Notion toggle read the same events, one way."""
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]},
        }
    )
    steps = web_live.steps(line)
    assert [step.line for step in steps] == ["Bash · npm test"]
    assert web_live.steps("not json at all") == []


@case
def a_ticket_finds_its_own_session_and_tells_what_the_agent_said_from_what_it_did():
    """The ticket page reads its journal by the ticket, not by a session id.

    What the agent said and what it ran are drawn differently there — the one
    read, the other folded — so each step says which it is, on the stream and
    in the log read back alike.
    """
    said = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Je lis le code."}]}}
    )
    ran = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
        }
    )
    with _state_home():
        logs = state.logs_dir()
        (logs / "20260830-120000-1a2b3c4d.jsonl").write_text(said + "\n" + ran + "\n", encoding="utf-8")
        (logs / "20260830-130000-99999999.jsonl").write_text(ran + "\n", encoding="utf-8")
        api = _bare_api(_TalkClient([]))
        found = api.logs("1a2b3c4d")["logs"]
        assert [entry["name"] for entry in found] == ["20260830-120000-1a2b3c4d.jsonl"], found
        assert len(api.logs()["logs"]) == 2
        read = api.log(found[0]["name"])
        assert read["count"] == 2
        assert [(step["label"], step["said"]) for step in read["steps"]] == [
            ("Je lis le code.", True),
            ("Bash", False),
        ]

        hub = web_live.Hub()
        published = []
        hub.publish = lambda kind, **payload: published.append((kind, payload))  # type: ignore[method-assign]
        web_live.Tail(hub, logs).pass_once()
        told = [payload for kind, payload in published if kind == "step" and payload["source"] == "1a2b3c4d"]
        assert [payload["said"] for payload in told] == [True, False], told


@case
def a_session_log_is_tailed_forward_and_never_twice():
    hub = web_live.Hub()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        log = folder / "20260830-120000-1a2b3c4d.jsonl"
        event = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "reading"}]}}
        )
        log.write_text(event + "\n", encoding="utf-8")
        tail = web_live.Tail(hub, folder)
        assert tail.pass_once() == 1
        assert tail.pass_once() == 0, "a pass that adds nothing must publish nothing"

        # A half-written line is left for the next pass rather than dropped.
        with log.open("a", encoding="utf-8") as handle:
            handle.write(event[:20])
        assert tail.pass_once() == 0
        with log.open("a", encoding="utf-8") as handle:
            handle.write(event[20:] + "\n")
        assert tail.pass_once() == 1


@case
def the_board_is_published_only_when_it_has_moved():
    """A poll that redrew an unchanged board would lose your scroll for nothing."""
    hub = web_live.Hub()
    boards = [{"tickets": [{"id": "a", "title": "one"}]}, {"tickets": [{"id": "a", "title": "one"}]},
              {"tickets": [{"id": "a", "title": "two"}]}]
    watch = web_live.Watch(hub, lambda: boards.pop(0), interval=5)
    channel = hub.subscribe()
    watch.refresh()
    watch.refresh()
    watch.refresh()
    published = [channel.get_nowait() for _ in range(channel.qsize())]
    assert [event.kind for event in published] == ["board", "changes"], published
    assert published[1].payload == {
        "changed": [{"after": "", "ticket": {"id": "a", "title": "two"}}],
        "removed": [],
        "base": 1,
        "version": 2,
    }, published[1].payload


def _tickets(*cards: tuple[str, str, str]) -> dict:
    """A board as `Api.board` sorts it: by column, then by title."""
    order = ["ready", "running", "review"]
    tickets = [{"id": i, "column": c, "title": t, "steps": 0} for i, c, t in cards]
    tickets.sort(key=lambda item: (order.index(item["column"]), item["title"]))
    return {"tickets": tickets, "validate": False, "columns": [{"key": k, "name": k} for k in order]}


def _apply(board: dict, changes: dict) -> list[dict]:
    """What `applyChanges` in `board-store.ts` does with them, line for line."""
    gone = set(changes["removed"]) | {entry["ticket"]["id"] for entry in changes["changed"]}
    tickets = [ticket for ticket in board["tickets"] if ticket["id"] not in gone]
    for entry in changes["changed"]:
        at = next(i for i, t in enumerate(tickets) if t["id"] == entry["after"]) + 1 if entry["after"] else 0
        tickets.insert(at, entry["ticket"])
    return tickets


@case
def a_board_that_moved_is_sent_as_what_moved_and_gives_back_the_same_board():
    """A card moved, one added, one gone: the page rebuilds exactly the board, in its order."""
    before = _tickets(("a", "ready", "Alpha"), ("b", "ready", "Beta"), ("c", "running", "Gamma"),
                      ("d", "review", "Delta"))
    after = _tickets(("a", "running", "Alpha"), ("b", "ready", "Beta"), ("c", "running", "Gamma"),
                     ("e", "ready", "Epsilon"))
    changes = web_live.difference(before, after)
    assert changes is not None
    assert [entry["ticket"]["id"] for entry in changes["changed"]] == ["e", "a"], changes
    assert changes["removed"] == ["d"]
    assert _apply(before, changes) == after["tickets"]

    # The same board again says nothing has changed; new columns need the whole board.
    assert web_live.difference(after, after) == {"changed": [], "removed": []}
    renamed = {**after, "columns": [{"key": "ready", "name": "Prêt"}]}
    assert web_live.difference(after, renamed) is None
    assert web_live.difference(None, after) is None


@case
def a_ticket_in_flight_costs_the_stream_its_own_card_not_the_board():
    """475 tickets, one step further on one of them: under 10 KB, where the board is ~360."""
    filler = "x" * 600
    cards = [{"id": f"{n:032x}", "column": "backlog", "title": f"Ticket {n:03d}", "brief": filler}
             for n in range(475)]
    board = {"tickets": cards, "validate": True, "columns": [{"key": "backlog", "name": "Backlog"}]}
    moved = {**board, "tickets": [dict(card) for card in cards]}
    moved["tickets"][200]["steps"] = 42
    hub = web_live.Hub()
    watch = web_live.Watch(hub, iter([board, moved]).__next__)
    channel = hub.subscribe()
    watch.refresh()
    watch.refresh()
    whole, step = (channel.get_nowait() for _ in range(2))
    assert step.kind == "changes"
    assert len(whole.encode().encode()) > 300_000
    assert len(step.encode().encode()) < 10_000, len(step.encode().encode())


@case
def a_browser_is_given_the_whole_board_again_only_when_it_missed_a_version():
    hub = web_live.Hub()
    watch = web_live.Watch(hub, iter([
        _tickets(("a", "ready", "Alpha")),
        _tickets(("a", "running", "Alpha")),
    ]).__next__)
    watch.refresh()  # event 1: the whole board
    hub.publish("step", label="Read")  # event 2
    watch.refresh()  # event 3: what changed

    fresh = hub.subscribe()
    first = fresh.get_nowait()
    assert (first.kind, first.payload["version"]) == ("board", 2), "a new tab gets it whole, as it is now"
    assert first.payload["tickets"][0]["column"] == "running"

    up_to_date = hub.subscribe(after=3)
    assert up_to_date.qsize() == 0, "a tab that saw the last changes is not sent the board again"

    behind = hub.subscribe(after=2)
    kinds = [behind.get_nowait().kind for _ in range(behind.qsize())]
    assert kinds == ["board"], "missed changes are replaced by the whole board, never replayed"

    lost = hub.subscribe(after=3, board=True)
    assert [lost.get_nowait().kind for _ in range(lost.qsize())] == ["board"]


@case
def a_write_from_the_console_that_changed_nothing_sends_the_board_whole():
    """The page drew the card ahead; a board that did not move puts it back."""
    board = _tickets(("a", "ready", "Alpha"))
    hub = web_live.Hub()
    watch = web_live.Watch(hub, lambda: board)
    channel = hub.subscribe()
    watch.refresh()
    watch.refresh(force=True)
    watch.refresh()
    assert [channel.get_nowait().kind for _ in range(channel.qsize())] == ["board", "board"]


@case
def a_notion_that_will_not_answer_reaches_the_console_as_a_notice():
    """Named `notice`: EventSource already fires an `error` of its own."""
    hub = web_live.Hub()
    said = []
    hub.publish = lambda kind, **payload: said.append((kind, payload))  # type: ignore[method-assign]

    def broken() -> dict:
        raise notion.NotionError("object not found\nsecond line nobody needs")

    web_live.Watch(hub, broken).refresh()
    assert said == [("notice", {"where": "board", "message": "object not found"})]


@case
def a_session_identifier_is_read_from_either_shape_of_the_column():
    """A URL column holds a link, a text column holds the bare ID. Same session."""
    from ponos.web.api import _session_id

    identifier = "6f1c2b70-1c39-4f0a-9a52-1f3c1a2b3c4d"
    assert _session_id(identifier) == identifier
    assert _session_id(session.deep_link(identifier, cwd="/home/me/work")) == identifier
    assert _session_id(session.deep_link(identifier, host="server")) == identifier
    assert _session_id("") == ""


@case
def the_console_only_listens_beyond_localhost_when_told_to():
    """Behind the port sits bypassPermissions: a generated token is not consent."""
    from ponos.web import server as web_server

    configuration = C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(host="0.0.0.0"),
    )
    explained = io.StringIO()
    with contextlib.redirect_stdout(explained):
        assert web_server.serve(configuration, announce=False) == 2, "must refuse, not serve"
    said = explained.getvalue()
    assert "bypassPermissions" in said, "and say why, not just refuse"
    assert "web.email" in said, "and name both ways of saying it on purpose"


def _web_config(**web) -> C.Config:
    """A configuration that is nothing but its [web] table."""
    return C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(**web),
    )


@case
def an_email_and_a_password_are_a_way_into_the_console():
    """A token is right for a script and tiring for a person.

    The cookie a sign-in leaves is derived from the two rather than drawn, and
    that is the whole of the session handling: the console's unit restarts with
    the machine, and a browser that had to sign in again every morning would be
    the token all over again.
    """
    from ponos.web import server as web_server

    assert web_server.sign_in(_web_config(), "tok") is None
    assert web_server.sign_in(_web_config(email="me@example.com"), "tok") is None, (
        "half a sign-in is somebody configuring one, not a way in"
    )
    assert web_server.sign_in(_web_config(password="hunter2"), "tok") is None

    entry = web_server.sign_in(_web_config(email="Me@Example.com", password="hunter2"), "tok")
    assert entry is not None and entry.email == "Me@Example.com"
    again = web_server.sign_in(_web_config(email="me@example.com", password="hunter2"), "tok")
    assert entry.cookie == again.cookie, "a restart, or a capital, must not sign anybody out"
    assert "hunter2" not in entry.cookie and entry.cookie != "tok"
    changed = web_server.sign_in(_web_config(email="me@example.com", password="hunter3"), "tok")
    assert changed.cookie != entry.cookie, "a new password signs every browser out"
    elsewhere = web_server.sign_in(_web_config(email="me@example.com", password="hunter2"), "other")
    assert elsewhere.cookie != entry.cookie, "the cookie belongs to this console's token"


@case
def a_token_in_the_address_is_taken_out_and_the_destination_left_in():
    """`?token=…&view=…` is one secret and one destination, and only one goes.

    The token is moved into a cookie and out of the address, because it would
    otherwise sit in the history and in every screenshot. What sits beside it is
    not a secret: `serve` prints `/?token=…`, and a link to a pane is shared as
    `/?token=…&view=console/projects/list`. Redirecting both to a bare `/` put
    the second one on the board.
    """
    from urllib.parse import parse_qs

    from ponos.web import server as web_server

    assert web_server.landing("token=abc") == "/", "nothing else to say: the console opens"
    assert web_server.landing("") == "/"
    kept = web_server.landing("token=abc&view=console/projects/list")
    assert "token" not in kept, "the secret stays in the cookie"
    assert parse_qs(kept.lstrip("/?"))["view"] == ["console/projects/list"], kept
    # Whatever the address carried, in the order it carried it.
    both = web_server.landing("view=console/projects/list&token=abc&variant=table")
    assert parse_qs(both.lstrip("/?")) == {
        "view": ["console/projects/list"],
        "variant": ["table"],
    }, both


@case
def the_sign_in_page_asks_the_way_the_console_does():
    """It posts rather than navigates, and carries the header every write does.

    A form that navigated could not set `X-Ponos`, which is what tells a
    request from the console apart from one a page you had open made — so the
    page written here has to agree with the constant the server checks.
    """
    from ponos.web import server as web_server

    assert web_server.GUARD_HEADER in web_server.SIGN_IN, "the login would be refused as CSRF"
    assert "/api/login" in web_server.SIGN_IN
    assert 'type="password"' in web_server.SIGN_IN
    for page in (web_server.GATE, web_server.SIGN_IN):
        assert "src=\"http" not in page and "href=\"http" not in page, "it reaches off the machine"


@case
def the_first_connection_is_offered_until_somebody_says_how_to_get_in():
    """A token protects an installation; a fresh one has nothing to protect yet.

    Two ways of deciding how the console is opened, and the page exists for the
    state where neither was taken. The token drawn on first start is not one of
    them: nobody chose it, and it is the very secret the first connection is
    there to stop somebody having to go and find.
    """
    from ponos.web import server as web_server

    bare = _web_config()
    assert web_server.claimable(bare, None), "a console nobody decided anything about"
    assert not web_server.claimable(_web_config(token="chosen"), None), (
        "a token in the file is a decision, and the gate is what it asks for"
    )
    entry = web_server.sign_in(_web_config(email="me@example.com", password="hunter22"), "tok")
    assert not web_server.claimable(bare, entry), "a sign-in closes it for good"


class _Fresh:
    """An `Api`, reduced to the three things a first connection asks of it.

    The real one rereads the file whenever its mtime moves, which is what makes
    a run of `apply` see the token it wrote two lines above; this does the same
    by hand, and nothing else.
    """

    def __init__(self, path: Path) -> None:
        self.config = C.load(path)
        self.context = ""

    def save_settings(self, payload: dict) -> dict:
        saved = web_settings.save(self.config, payload)
        self.config = C.load(self.config.path)
        return saved

    def save_context(self, text: str) -> dict:
        self.context = text.strip()
        return {"ok": True, "text": self.context}

    def forget(self) -> None:
        pass


@case
def the_first_connection_writes_the_whole_installation_at_once():
    """One form, and the file it leaves is one somebody could have typed.

    Every value written is a key of `config.toml` — saved through the console's
    own writer, floors and all — and the pair that matters most is the one that
    closes the page behind it: once the email and the password are in, the
    console is claimed and this is not a way in any more.
    """
    from ponos.web import server as web_server
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _Fresh(path)
    report = web_setup.apply(
        api,
        {
            "email": "me@example.com",
            "password": "one I remember",
            "confirm": "one I remember",
            "rules": "  I am Salva. Answer in French.  ",
            "telegram_token": "123:abc",
            "telegram_chat": "4242",
        },
    )
    assert report["problem"] == "", report
    assert report["steps"] and report["steps"][0][1].endswith("me@example.com from now on")

    written = path.read_text(encoding="utf-8")
    secrets = C.read_secrets(C.secrets_path(path))
    assert 'email = "me@example.com"' in written and "one I remember" not in written
    assert secrets["PONOS_WEB_PASSWORD"] == "one I remember", "a secret goes beside the file"
    assert 'chat = "4242"' in written and "123:abc" not in written
    assert secrets["PONOS_TELEGRAM_TOKEN"] == "123:abc"
    assert secrets["PONOS_NOTION_TOKEN"] == "ntn_real", "the rest is left where it was"
    assert api.context == "I am Salva. Answer in French.", "the rules reach every ticket"

    entry = web_server.sign_in(api.config, "tok")
    assert entry is not None and entry.email == "me@example.com"
    assert not web_server.claimable(api.config, entry), "the door it just built stays shut"


@case
def a_first_connection_that_cannot_be_signed_into_later_is_refused():
    """What is refused here is refused before anything is written.

    A password is guessable in a way a token is not, and behind this port sits a
    runner that runs code on this machine — so the floor is said in the form
    rather than discovered by whoever grinds against it.
    """
    from ponos.web import setup as web_setup

    path, _ = _saved()
    before = path.read_text(encoding="utf-8")
    for payload, expected in (
        ({"email": "me", "password": "one I remember"}, "email address"),
        ({"email": "me@example.com", "password": "short"}, "at the least"),
        (
            {"email": "me@example.com", "password": "one I remember", "confirm": "another"},
            "not the same",
        ),
        (
            {
                "email": "me@example.com",
                "password": "one I remember",
                "notion_page": "my notion page",
            },
            "Notion page ID",
        ),
    ):
        api = _Fresh(path)
        try:
            web_setup.apply(api, payload)
        except ValueError as error:
            assert expected in str(error), error
            continue
        raise AssertionError(f"{payload} should have been refused")
    assert path.read_text(encoding="utf-8") == before, "a refusal writes nothing"


def _talk_to(console, method: str, path: str, body: dict | None = None, **headers: str):
    """One request to a console started for the test: status, headers, JSON."""
    connection = http.client.HTTPConnection("127.0.0.1", console.server_address[1], timeout=10)
    sent = {"Host": "127.0.0.1", "X-Ponos": "1", "Content-Type": "application/json", **headers}
    connection.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                       headers=sent)
    answer = connection.getresponse()
    raw = answer.read()
    connection.close()
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        parsed = {"_raw": raw.decode("utf-8", "replace")}
    return answer.status, answer.headers, parsed


@contextmanager
def _console(api, code: str = "", entry=None):
    from ponos.web import server as web_server

    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok", entry, code)
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:
        yield console
    finally:
        console.shutdown()
        console.server_close()


@case
def from_outside_this_machine_nobody_claims_the_console_without_its_code():
    """A console behind a domain is a console the whole Internet reaches first.

    On loopback the first browser is somebody sitting at the machine. Anything
    else — another address, or this one through a proxy, which is what Traefik
    in front of a container is — has to give the code `serve` printed when it
    started. No code drawn, and the first connection is simply not offered.
    """
    from ponos.web import server as web_server

    claim = {"email": "me@example.com", "password": "one I remember", "confirm": "one I remember"}
    proxied = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}

    path, _ = _saved()
    before = path.read_text(encoding="utf-8")
    api = _Fresh(path)
    with _console(api) as console:
        status, _, said = _talk_to(console, "GET", "/api/setup", **proxied)
        assert status == 200 and said["claimed"] is False and said["code"] is True, said
        assert said["code_drawn"] is False
        status, _, said = _talk_to(console, "POST", "/api/setup", claim, **proxied)
        assert status == 403, (status, said)
        assert "installation code" in said["error"]
        status, _, said = _talk_to(console, "GET", "/", **proxied)
        assert status == 200 and 'data-setup="claim"' in said["_raw"], "the steps, drawn by the bundle"
        status, _, said = _talk_to(console, "GET", "/api/board", **proxied)
        assert status == 401, "and nothing else of the console"
    assert path.read_text(encoding="utf-8") == before, "a refusal writes nothing"
    assert web_server.claimable(api.config, None), "and the console is still nobody's"

    api = _Fresh(path)
    with _console(api, code="K7Q2-M9XD") as console:
        status, _, said = _talk_to(console, "POST", "/api/setup", {**claim, "code": "AAAA-BBBB"}, **proxied)
        assert status == 403 and said["error"] == "wrong installation code", said
        assert path.read_text(encoding="utf-8") == before
        status, headers, said = _talk_to(console, "POST", "/api/setup", {**claim, "code": "k7q2m9xd"}, **proxied)
        assert status == 200, said
        assert "ponos_token=" in headers["Set-Cookie"]
        assert console.code == "", "a code opens the door once"
    assert not web_server.claimable(api.config, web_server.sign_in(api.config, "tok"))

    # At the machine itself, nothing to give: that is a laptop's first browser.
    path, _ = _saved()
    api = _Fresh(path)
    with _console(api) as console:
        status, _, said = _talk_to(console, "GET", "/api/setup")
        assert said["code"] is False, said
        status, _, said = _talk_to(console, "POST", "/api/setup", claim)
        assert status == 200, said


@case
def a_containers_healthcheck_is_answered_without_a_key():
    """`/healthz` says the console answers, to anybody — and says nothing else."""
    path, _ = _saved()
    api = _Fresh(path)
    with _console(api, code="K7Q2-M9XD") as console:
        status, _, said = _talk_to(console, "GET", "/healthz")
        assert status == 200 and said == {"ok": True}, (status, said)
        status, _, said = _talk_to(console, "GET", "/healthz", **{"X-Forwarded-For": "203.0.113.9"})
        assert status == 200 and said == {"ok": True}, "from outside as well, claimed or not"
        status, _, _ = _talk_to(console, "GET", "/api/board")
        assert status == 401, "and it opens nothing else"


@case
def behind_https_the_consoles_cookies_are_secure():
    """The proxy says the browser came in over HTTPS: the cookie never goes back in clear.

    All three ways in — the token in the address, a sign-in, and the first
    connection — set the same cookie, and all three mark it `Secure` then.
    """
    from ponos.web import server as web_server

    path, _ = _saved('\n[web]\nemail = "me@example.com"\npassword = "one I remember"\n')
    api = _Fresh(path)
    entry = web_server.sign_in(api.config, "tok")
    https = {"X-Forwarded-Proto": "https"}
    with _console(api, entry=entry) as console:
        signing = {"email": "me@example.com", "password": "one I remember"}
        _, headers, _ = _talk_to(console, "POST", "/api/login", signing, **https)
        assert headers["Set-Cookie"].endswith("; Secure"), headers["Set-Cookie"]
        _, headers, _ = _talk_to(console, "POST", "/api/login", signing)
        assert "Secure" not in headers["Set-Cookie"], "plain HTTP on loopback has no use for it"
        status, headers, _ = _talk_to(console, "GET", "/?token=tok", **https)
        assert status == 303 and "; Secure" in headers["Set-Cookie"]

    path, _ = _saved()
    with _console(_Fresh(path)) as console:
        claim = {"email": "me@example.com", "password": "one I remember"}
        status, headers, said = _talk_to(console, "POST", "/api/setup", claim, **https)
    # Through a proxy, and so from outside: refused without a code — and with
    # one, below, the cookie it leaves is a secure one.
    assert status == 403, said
    path, _ = _saved()
    with _console(_Fresh(path), code="ABCD-EFGH") as console:
        status, headers, said = _talk_to(
            console, "POST", "/api/setup", {**claim, "code": "ABCD-EFGH"}, **https
        )
    assert status == 200 and "; Secure" in headers["Set-Cookie"], said


@contextmanager
def _environment(**values: str | None):
    """Some variables set — or taken away, for None — for the length of a block."""
    previous = {name: os.environ.get(name) for name in values}
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@case
def a_subscription_token_in_the_environment_is_a_signed_in_cli():
    """`claude setup-token` handed over as CLAUDE_CODE_OAUTH_TOKEN: the CLI works, and says how."""
    from ponos import provider

    answered = json.dumps({"loggedIn": True, "authMethod": "oauth_token"})
    original = provider.subprocess.run, provider.session.available
    provider.session.available = lambda: "/usr/bin/claude"
    provider.subprocess.run = lambda *_, **__: subprocess.CompletedProcess([], 0, answered, "")
    try:
        check = provider.cli_login()
    finally:
        provider.subprocess.run, provider.session.available = original
    assert check.ok and "CLAUDE_CODE_OAUTH_TOKEN" in check.said, check


@case
def a_file_with_no_provider_runs_its_sessions_where_it_always_did():
    """`claude.provider` is a choice; a file written before it is not moved anywhere."""
    from ponos import provider

    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        _, plain = _saved()
        assert provider.chosen(plain) == "cli" and provider.environment(plain) == {}
        _, routed = _saved('\n[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n')
        assert provider.chosen(routed) == "openrouter"
        assert provider.environment(routed)["ANTHROPIC_AUTH_TOKEN"] == "sk-or-1234567890"

        # Chosen on purpose, the provider wins over a key that is only there.
        _, cli = _saved(
            '\n[claude]\nprovider = "cli"\n[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n'
        )
        given = provider.environment(cli)
        assert "ANTHROPIC_AUTH_TOKEN" not in given and "ANTHROPIC_BASE_URL" not in given
        assert given["OPENROUTER_API_KEY"] == "sk-or-1234567890", "still there for the work"

        _, keyed = _saved('\n[claude]\nprovider = "api_key"\napi_key = "sk-ant-abcdefghijkl"\n')
        assert provider.environment(keyed) == {"ANTHROPIC_API_KEY": "sk-ant-abcdefghijkl"}
        assert provider.describe(keyed) == ("Anthropic API key", "sk-ant…ijkl")
        _, typo = _saved('\n[claude]\nprovider = "anthropic"\n')
        assert typo.claude.provider == "" and provider.chosen(typo) == "cli"

        _, empty = _saved('\n[claude]\nprovider = "api_key"\n')
        assert "ANTHROPIC_API_KEY" in provider.problem(empty)
        # The CLI's session is never handed the key it would sign in with instead.
        _, cli_keyed = _saved('\n[claude]\nprovider = "cli"\napi_key = "sk-ant-abcdefghijkl"\n')
        assert provider.environment(cli_keyed) == {}

    # A container is given its keys in the environment; the file still wins.
    with _environment(ANTHROPIC_API_KEY="sk-ant-from-env-0000", OPENROUTER_API_KEY="sk-or-env-0000"):
        _, bare = _saved()
        assert bare.claude.api_key == "sk-ant-from-env-0000"
        assert bare.openrouter.key == "sk-or-env-0000"
        _, written = _saved('\n[claude]\napi_key = "sk-ant-typed"\n')
        assert written.claude.api_key == "sk-ant-typed"
        assert provider.problem(_saved('\n[claude]\nprovider = "api_key"\n')[1]) == ""


@case
def only_the_cli_waits_for_credits():
    """A key is billed as it is used: no window to wait for, no share to reserve."""
    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        assert Runner(_saved()[1], quiet=True)._waits_for_credits
        keyed = _saved('\n[claude]\nprovider = "api_key"\napi_key = "sk-ant-abcdefghijkl"\n')[1]
        assert not Runner(keyed, quiet=True)._waits_for_credits
        routed = _saved('\n[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n')[1]
        assert not Runner(routed, quiet=True)._waits_for_credits


@case
def doctor_says_which_provider_answers_and_counts_one_that_cannot():
    from ponos.__main__ import _doctor_provider

    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert _doctor_provider(_saved('\n[claude]\nprovider = "api_key"\n')[1]) == 1
        assert "Anthropic API key" in out.getvalue() and "ANTHROPIC_API_KEY" in out.getvalue()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            routed = '\n[claude]\nprovider = "openrouter"\n[openrouter]\nkey = "sk-or-1234567890"\n'
            assert _doctor_provider(_saved(routed)[1]) == 0
        said = out.getvalue()
        assert 'claude.provider = "openrouter"' in said and "sk-or-…7890" in said
        assert "route_sessions = false" in said, "a provider whose sessions are not on it is said"


@case
def the_first_connection_writes_the_provider_only_once_it_answers():
    """A key that does not work, saved, is a ticket that fails on it in the night."""
    from ponos import provider
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _Fresh(path)
    original = provider.api_key, provider.openrouter_key, provider.cli_login
    try:
        provider.api_key = lambda key: provider.Check(key == "sk-ant-good", "checked")
        provider.openrouter_key = lambda key, base="": provider.Check(key == "sk-or-good", "checked")
        provider.cli_login = lambda: provider.Check(False, "not signed in — claude auth login")
        with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
            said = web_setup.save_provider(api, {"provider": "api_key", "key": "sk-ant-bad"})
            assert said["ok"] is False and "api_key" not in path.read_text(encoding="utf-8")
            said = web_setup.save_provider(api, {"provider": "api_key", "key": "sk-ant-good"})
            assert said["ok"] and api.config.claude.provider == "api_key"
            assert api.config.claude.api_key == "sk-ant-good"
            said = web_setup.save_provider(
                api, {"provider": "openrouter", "key": "sk-or-good", "route_sessions": True}
            )
            assert said["ok"] and provider.chosen(api.config) == "openrouter"
            assert api.config.openrouter.route_sessions is True
            # The CLI is written at once: what it needs is typed in a terminal.
            said = web_setup.save_provider(api, {"provider": "cli"})
            assert said["ok"] is False and said["command"] == "claude auth login"
            assert api.config.claude.provider == "cli"
            try:
                web_setup.save_provider(api, {"provider": "bedrock"})
            except ValueError:
                pass
            else:
                raise AssertionError("an unknown provider is refused")
    finally:
        provider.api_key, provider.openrouter_key, provider.cli_login = original


@case
def in_a_container_a_new_version_is_a_new_image():
    """No link to move and no unit to restart: the image is the version."""
    from ponos.web import upgrade as web_upgrade

    with _environment(PONOS_CONTAINER="1"), _state_home():
        status = update.check()
        assert status.reason == update.CONTAINER and not status.stale
        assert update.apply(update.Status(current="a", latest="b"), 60) == update.CONTAINER
        said: list[str] = []
        update.between_runs(C.Runner(), say=said.append, notify=lambda *_: None)
        assert said == [], "nothing to say once an hour about something that cannot happen"
        upgrade = web_upgrade.Upgrade(lambda *a, **k: None, C.Runner)
        offer = upgrade.offer()
        assert offer["automatic"] is False and "new image" in offer["manual"]
        assert offer["command"] == update.PULL
        try:
            upgrade.start()
        except RuntimeError as error:
            assert "new image" in str(error)
        else:
            raise AssertionError("no update starts in a container")


@case
def a_loop_of_runs_takes_the_lock_like_the_timer_did():
    """`run --every` starts `ponos run` itself, and a run already going turns it away."""
    from ponos.__main__ import run_every

    root = Path(tempfile.mkdtemp())
    config = root / "config.toml"
    config.write_text(f'[storage]\nmode = "markdown"\npath = "{root / "board"}"\n', encoding="utf-8")
    arguments = build_parser().parse_args(["run", "--every", "1"])
    assert arguments.every == 1
    assert build_parser().parse_args(["run", "--every"]).every == 0, "the configuration's interval"
    with _environment(PONOS_CONFIG=str(config)), _state_home():
        with state.lock():
            answered = subprocess.run(
                [sys.executable, "-c", (
                    "import sys; from ponos.__main__ import run_every, build_parser;"
                    "sys.exit(run_every(build_parser().parse_args(['run', '--every', '1']), passes=2))"
                )],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            )
        assert answered.returncode == 0, answered.stderr
        assert answered.stdout.count("a run is already in progress") == 2, answered.stdout


@case
def the_consoles_sign_in_may_live_in_the_environment_rather_than_the_file():
    """A server has somewhere better to put a password than a file you read out.

    The environment wins, which is what makes it worth setting — and what comes
    out of it is stripped, because a password read out of a file carries the
    newline that file ends with and would lock you out of your own console.
    """
    path, config = _saved('\n[web]\nemail = "file@example.com"\npassword = "written down"\n')
    assert config.web.email == "file@example.com" and config.web.password == "written down"

    previous = {name: os.environ.get(name) for name in (C.WEB_EMAIL_ENV, C.WEB_PASSWORD_ENV)}
    os.environ[C.WEB_EMAIL_ENV] = "unit@example.com"
    os.environ[C.WEB_PASSWORD_ENV] = "from the unit\n"
    try:
        fresh = C.load(path)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert fresh.web.email == "unit@example.com"
    assert fresh.web.password == "from the unit"


@contextmanager
def _environ(**values: str):
    """Variables set for the length of a block, and put back as they were."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@case
def a_secret_left_in_config_toml_is_never_read():
    """The file is copied into images and pasted into tickets: no secret in it.

    Every key `SECRETS` names is ignored there, and said to be — `exposed` is
    what the launch and `doctor` read to tell somebody.
    """
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntoken = "ntn_real"\nworkspace = "3a8451680af480918afcf0eb9cf70e7b"\n'
        '[web]\ntoken = "tok"\npassword = "pw"\n[claude]\napi_key = "sk-ant-x"\n'
        '[openrouter]\nkey = "sk-or-x"\n'
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n[notify.slack]\ntoken = "xoxb-1"\n'
    )
    config = C.load(path)
    assert not config.notion.token and not config.web.token and not config.web.password
    assert not config.claude.api_key and not config.openrouter.key
    assert "token" not in config.notify.telegram and config.notify.telegram["chat"] == "42"
    assert "token" not in config.notify.slack
    assert set(config.exposed) == {f"{table}.{key}" for table, key in C.SECRETS}
    try:
        config.require_usable()
    except C.ConfigError as error:
        assert "PONOS_NOTION_TOKEN" in str(error) and "secrets.env" in str(error), error
    else:
        raise AssertionError("a token only config.toml holds is no token")

    # The example's placeholder is where a token went, not one.
    path.write_text('[notion]\ntoken = "%s"\n' % C.PLACEHOLDER)
    assert C.load(path).exposed == ()


@case
def a_launch_moves_the_secrets_out_of_config_toml_and_says_so():
    """An installation that updates itself must not wake up without its token.

    Moved, not copied: the file and its backup are left with no secret in them,
    the comments around stay, and `secrets.env` is private from its first byte.
    A variable secrets.env already holds was put there later: it is kept.
    """
    from ponos import __main__ as cli

    folder = Path(tempfile.mkdtemp())
    path = folder / "config.toml"
    text = (
        '[notion]\n# the integration\ntoken = "ntn_real"\nworkspace = "w"\n'
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
        '[openrouter]\nkey = "sk-or-old"\n'
    )
    path.write_text(text)
    path.chmod(0o640)
    (folder / "config.toml.bak").write_text(text)
    C.write_secrets(C.secrets_path(path), {"OPENROUTER_API_KEY": "sk-or-new"})

    said: list[str] = []
    with _environ(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert len(said) == 1 and "notion.token" in said[0] and "secrets.env" in said[0], said

    stored = C.read_secrets(C.secrets_path(path))
    assert stored == {
        "PONOS_NOTION_TOKEN": "ntn_real",
        "PONOS_TELEGRAM_TOKEN": "123:abc",
        "OPENROUTER_API_KEY": "sk-or-new",
    }, stored
    assert (C.secrets_path(path).stat().st_mode & 0o777) == 0o600
    for left in (path, folder / "config.toml.bak"):
        written = left.read_text()
        assert "ntn_real" not in written and "123:abc" not in written and "sk-or" not in written
        assert "# the integration" in written and 'chat = "42"' in written
    assert (path.stat().st_mode & 0o777) == 0o640, "the file keeps its own mode"

    config = C.load(path)
    assert config.notion.token == "ntn_real" and config.notify.telegram["token"] == "123:abc"
    assert config.openrouter.key == "sk-or-new" and config.exposed == ()

    said.clear()
    with _environ(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert said == [], "a second launch has nothing to say"

    C.secrets_path(path).chmod(0o644)
    with _environ(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert said and "chmod 600" in said[0], said


@case
def the_console_writes_a_secret_beside_the_file_never_in_it():
    """The Settings tab and the first connection save through `config.edit`."""
    path, config = _saved('\n[claude]\nprovider = "api_key"\n')
    saved = web_settings.save(
        config, {"settings": {"claude.api_key": "sk-ant-typed", "runner.max_concurrent": 3}}
    )
    assert set(saved["saved"]) == {"claude.api_key", "runner.max_concurrent"}, saved
    written = path.read_text()
    assert "sk-ant-typed" not in written and "max_concurrent = 3" in written
    assert C.read_secrets(C.secrets_path(path))["ANTHROPIC_API_KEY"] == "sk-ant-typed"
    assert "sk-ant" not in (path.parent / "config.toml.bak").read_text()

    fresh = C.load(path)
    assert fresh.claude.api_key == "sk-ant-typed"
    field = next(
        item
        for section in web_settings.describe(fresh)["sections"]
        for item in section["fields"]
        if item["name"] == "claude.api_key"
    )
    assert field["stated"] and field["preview"] == "…yped" and field["value"] == ""

    web_settings.save(fresh, {"settings": {"claude.api_key": None}})
    assert "ANTHROPIC_API_KEY" not in C.read_secrets(C.secrets_path(path))
    assert C.read_secrets(C.secrets_path(path))["PONOS_NOTION_TOKEN"] == "ntn_real"


@case
def a_typed_key_wins_over_the_environment_and_the_environment_over_a_password():
    """Who wrote it last: the console writes secrets.env, a compose file the
    environment — except for the sign-in, which the environment is there to claim."""
    path, _ = _saved()
    C.write_secrets(
        C.secrets_path(path), {"ANTHROPIC_API_KEY": "typed", "PONOS_WEB_PASSWORD": "typed too"}
    )
    with _environ(ANTHROPIC_API_KEY="composed", PONOS_WEB_PASSWORD="from the unit",
                  PONOS_SLACK_TOKEN="xoxb-env"):
        config = C.load(path)
    assert config.claude.api_key == "typed"
    assert config.web.password == "from the unit"
    assert config.notify.slack == {"token": "xoxb-env"}, "the environment alone is enough"


@case
def secrets_env_reads_what_a_shell_and_compose_read():
    """One file for `source`, `env_file` and `EnvironmentFile` — and for us."""
    path = Path(tempfile.mkdtemp()) / "secrets.env"
    awkward = 'a "quoted" pass $HOME `x` \\ end'
    assert C.write_secrets(path, {"PONOS_WEB_PASSWORD": awkward, "PONOS_WEB_TOKEN": "t0k"}) == [
        "PONOS_WEB_PASSWORD",
        "PONOS_WEB_TOKEN",
    ]
    assert C.read_secrets(path) == {"PONOS_WEB_PASSWORD": awkward, "PONOS_WEB_TOKEN": "t0k"}
    shell = subprocess.run(
        ["sh", "-c", f'. "{path}"; printf %s "$PONOS_WEB_PASSWORD"'],
        capture_output=True, text=True,
    )
    assert shell.stdout == awkward, shell.stdout

    path.write_text("# mine\nexport OTHER='kept'\nPONOS_WEB_TOKEN=old\n")
    assert C.write_secrets(path, {"PONOS_WEB_TOKEN": "new"}) == ["PONOS_WEB_TOKEN"]
    assert C.write_secrets(path, {"PONOS_WEB_TOKEN": "new"}) == [], "nothing moved, nothing written"
    assert path.read_text() == "# mine\nexport OTHER='kept'\nPONOS_WEB_TOKEN=new\n"
    assert C.read_secrets(path)["OTHER"] == "kept"


class _TalkClient:
    """A page with a discussion on it, and whatever gets written back."""

    def __init__(self, comments: list[notion.Comment]) -> None:
        self._comments = comments
        self.written: list[tuple[str, str, str]] = []

    def comments(self, page_id: str) -> list[notion.Comment]:
        return list(self._comments)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.written.append((page_id, text, discussion_id))


# -- statistics --------------------------------------------------------------


def _card(key: str, column: str, created: str, edited: str = "", project: str = "") -> dict:
    return {"id": key, "column": column, "created": created, "edited": edited, "project": project}


@case
def a_closing_is_dated_by_the_runner_before_the_last_edit():
    """The history says the minute the runner closed a ticket; an edit since does not move it.

    And a session that opened a pull request reports "done" without closing
    anything: that line is no closing.
    """
    from datetime import date

    history = [
        {"at": "2026-09-02T10:00:00+00:00", "id": "a", "status": "done", "pull_request": "u"},
        {"at": "2026-09-05T10:00:00+00:00", "id": "a", "status": "done", "merged": "u"},
        {"at": "2026-09-06T10:00:00+00:00", "id": "b", "status": "done", "kind": "document"},
        {"at": "2026-09-07T10:00:00+00:00", "id": "c", "status": "done", "pull_request": "u"},
    ]
    tickets = [
        _card("a", "done", "2026-09-01T09:00:00.000Z", edited="2026-09-20T09:00:00.000Z"),
        _card("b", "done", "2026-09-01T09:00:00.000Z", edited="2026-09-06T10:01:00.000Z"),
        # Merged by hand, closed by `close_merged`: no history line, its edit says when.
        _card("c", "done", "2026-09-01T09:00:00.000Z", edited="2026-09-08T09:00:00.000Z"),
    ]
    figures = web_statistics.figures(
        tickets, history, date(2026, 9, 1), date(2026, 9, 10), timezone.utc
    )
    closed = {item["day"]: item["closed"] for item in figures["days"] if item["closed"]}
    assert closed == {"2026-09-05": 1, "2026-09-06": 1, "2026-09-08": 1}, closed
    assert figures["dated"] == {"history": 2, "edited": 1}


@case
def the_open_curve_starts_from_the_board_as_it_stood_and_ends_on_it():
    """What is open on the last day is what the board shows as not done.

    A ticket from before the period counts from the first point, not from its
    creation; one created and closed the same day is never open overnight;
    blocked and failed are still open.
    """
    from datetime import date

    tickets = [
        _card("old", "blocked", "2026-07-01T09:00:00.000Z", project="Opoil"),
        _card("gone", "done", "2026-07-01T09:00:00.000Z", edited="2026-09-03T09:00:00.000Z"),
        _card("quick", "done", "2026-09-02T09:00:00.000Z", edited="2026-09-02T18:00:00.000Z"),
        _card("new", "ready", "2026-09-04T09:00:00.000Z", project="Opoil"),
        _card("failed", "failed", "2026-09-04T12:00:00.000Z", project="ponos"),
    ]
    history = [
        {"at": "2026-09-02T12:00:00+00:00", "id": "quick", "status": "done", "cost_usd": 1.5},
        {"at": "2026-09-04T12:00:00+00:00", "id": "new", "status": "blocked", "cost_usd": 0.25},
        {"at": "2026-08-01T12:00:00+00:00", "id": "old", "status": "blocked", "cost_usd": 9},
    ]
    figures = web_statistics.figures(
        tickets, history, date(2026, 9, 1), date(2026, 9, 5), timezone.utc
    )
    opened = [item["open"] for item in figures["days"]]
    assert opened == [2, 2, 1, 3, 3], opened
    assert figures["totals"] == {"open": 3, "closed": 2, "created": 3, "cost": 1.75}, figures["totals"]
    assert [item["cost"] for item in figures["days"]] == [0, 1.5, 1.5, 1.75, 1.75]
    assert {item["name"]: item["count"] for item in figures["projects"]} == {
        "": 1,
        "Opoil": 1,
        "ponos": 1,
    }
    assert {item["key"]: item["count"] for item in figures["statuses"]} == {
        "done": 1,
        "ready": 1,
        "failed": 1,
    }


@case
def a_cancelled_ticket_is_neither_closed_nor_open_and_keeps_its_cost():
    """Given up on is not done, and not somebody's to deal with any more.

    It leaves the open curve on its last edit without being counted closed,
    and what its sessions spent stays in the spending: the money is gone.
    """
    from datetime import date

    tickets = [
        _card("kept", "ready", "2026-09-01T09:00:00.000Z"),
        _card("dropped", "cancelled", "2026-09-01T09:00:00.000Z", edited="2026-09-03T09:00:00.000Z"),
    ]
    history = [
        {"at": "2026-09-02T12:00:00+00:00", "id": "dropped", "status": "blocked", "cost_usd": 2.0},
    ]
    figures = web_statistics.figures(
        tickets, history, date(2026, 9, 1), date(2026, 9, 4), timezone.utc
    )
    assert [item["open"] for item in figures["days"]] == [2, 2, 1, 1]
    assert figures["totals"] == {"open": 1, "closed": 0, "created": 2, "cost": 2.0}, figures["totals"]
    assert figures["average"] is None, "no ticket closed, none averaged"
    assert {item["key"]: item["count"] for item in figures["statuses"]} == {"ready": 1, "cancelled": 1}


@case
def the_open_tickets_of_the_last_day_are_the_boards_not_closed_ones():
    """Open on the evening of today is every card but done, validated and cancelled.

    Validated is approved and left to the runner to merge: nothing is left for
    anybody, so it leaves the open ones — dated by the edit that moved it,
    which is all the board says until the runner's history dates the merge.
    """
    from datetime import date

    columns = ("draft", "ready", "running", "blocked", "review", "validated", "done", "cancelled")
    tickets = [
        _card(column, column, "2026-09-01T09:00:00.000Z", edited="2026-09-03T09:00:00.000Z")
        for column in columns
    ]
    figures = web_statistics.figures(
        tickets, [], date(2026, 9, 1), date(2026, 9, 4), timezone.utc
    )
    board = sum(1 for ticket in tickets if ticket["column"] not in ("done", "validated", "cancelled"))
    assert [item["open"] for item in figures["days"]] == [8, 8, board, board], figures["days"]
    assert figures["totals"]["open"] == board == 5
    assert [item["closed"] for item in figures["days"]] == [0, 0, 2, 0]


@case
def the_tickets_created_are_handed_by_type_sub_type_and_project():
    """Cells the console filters on the spot, day by day up to a month, and the period before.

    A code ticket with no sub-type, or one the table does not know, is a cell
    with none — unclassified, still counted — and the period before is the
    one of the same length that ends the day before.
    """
    from datetime import date

    def card(key: str, created: str, kind: str, subtype: str = "", project: str = "") -> dict:
        return {**_card(key, "ready", created, project=project), "type": kind, "subtype": subtype}

    tickets = [
        card("a", "2026-09-08T09:00:00.000Z", "Code", "bug", "Opoil"),
        card("b", "2026-09-08T10:00:00.000Z", "Code", "bug", "Opoil"),
        card("c", "2026-09-09T09:00:00.000Z", "Code", "feature", "ponos"),
        card("d", "2026-09-09T09:00:00.000Z", "Code", "", "ponos"),
        card("e", "2026-09-10T09:00:00.000Z", "Rédaction", "", "ponos"),
        card("f", "2026-09-10T09:00:00.000Z", "Code", "made-up", "ponos"),
        # The week before: compared with, not drawn.
        card("g", "2026-09-02T09:00:00.000Z", "Code", "feature", "Opoil"),
        # Before that: neither.
        card("h", "2026-08-20T09:00:00.000Z", "Code", "bug", "Opoil"),
    ]
    kinds = {"code": "code", "rédaction": "writing"}
    figures = web_statistics.figures(
        tickets, [], date(2026, 9, 7), date(2026, 9, 13), timezone.utc,
        kind_of=lambda option: kinds.get(option.casefold(), ""),
    )
    made = figures["made"]
    assert made["unit"] == "day"
    assert made["buckets"][0] == "2026-09-07" and len(made["buckets"]) == 7
    assert made["cells"] == [
        {"bucket": "2026-09-08", "kind": "code", "subtype": "bug", "project": "Opoil", "count": 2},
        {"bucket": "2026-09-09", "kind": "code", "subtype": "", "project": "ponos", "count": 1},
        {"bucket": "2026-09-09", "kind": "code", "subtype": "feature", "project": "ponos", "count": 1},
        {"bucket": "2026-09-10", "kind": "code", "subtype": "", "project": "ponos", "count": 1},
        {"bucket": "2026-09-10", "kind": "writing", "subtype": "", "project": "ponos", "count": 1},
    ], made["cells"]
    assert made["before"] == [{"kind": "code", "subtype": "feature", "project": "Opoil", "count": 1}]

    # Past a month, a bucket is a week, named by its Monday.
    longer = web_statistics.figures(tickets, [], date(2026, 8, 1), date(2026, 9, 13), timezone.utc)
    assert longer["made"]["unit"] == "week"
    assert longer["made"]["buckets"][:2] == ["2026-07-27", "2026-08-03"]
    assert {cell["bucket"] for cell in longer["made"]["cells"]} == {"2026-08-17", "2026-08-31", "2026-09-07"}
    # No type said: none of the four.
    assert {cell["kind"] for cell in longer["made"]["cells"]} == {""}


@case
def the_projects_figures_add_up_to_the_boards():
    """Created and spent, project by project, are the board's — less the tickets with no project.

    A project's figures are the board's over its tickets alone, and its
    sessions are the history lines of those tickets. A line about a ticket the
    board no longer has belongs to nobody, so it is in the global spend only.
    """
    from datetime import date

    tickets = [
        _card("a", "done", "2026-09-02T09:00:00.000Z", edited="2026-09-04T09:00:00.000Z", project="Opoil"),
        _card("b", "ready", "2026-09-03T09:00:00.000Z", project="Opoil"),
        _card("c", "review", "2026-09-03T10:00:00.000Z", project="ponos"),
        _card("d", "ready", "2026-09-04T10:00:00.000Z"),
    ]
    history = [
        {"at": "2026-09-02T12:00:00+00:00", "id": "a", "status": "done", "kind": "document", "cost_usd": 1.0},
        {"at": "2026-09-03T12:00:00+00:00", "id": "b", "status": "blocked", "cost_usd": 0.5},
        {"at": "2026-09-03T13:00:00+00:00", "id": "c", "status": "done", "cost_usd": 2.0},
        {"at": "2026-09-04T13:00:00+00:00", "id": "d", "status": "blocked", "cost_usd": 4.0},
        {"at": "2026-09-04T14:00:00+00:00", "id": "gone", "status": "done", "cost_usd": 8.0},
    ]
    first, last = date(2026, 9, 1), date(2026, 9, 10)
    whole = web_statistics.figures(tickets, history, first, last, timezone.utc)
    by_project = {
        name: web_statistics.figures(tickets, history, first, last, timezone.utc, project=name)
        for name in ("Opoil", "ponos", "")
    }
    assert whole["totals"]["created"] == sum(f["totals"]["created"] for f in by_project.values())
    assert whole["totals"]["closed"] == sum(f["totals"]["closed"] for f in by_project.values())
    # 8.0 is a session of a ticket that left the board: in the whole only.
    assert whole["totals"]["cost"] == 15.5
    assert sum(f["totals"]["cost"] for f in by_project.values()) == 7.5
    assert by_project["Opoil"]["totals"] == {"open": 1, "closed": 1, "created": 2, "cost": 1.5}
    assert by_project[""]["totals"]["cost"] == 4.0
    # One closed ticket, 1.0 spent on it.
    assert by_project["Opoil"]["average"] == 1.0
    assert by_project["ponos"]["average"] is None
    assert [item["name"] for item in by_project["Opoil"]["projects"]] == ["Opoil"]


@case
def a_day_is_this_machines_day():
    """23:30 in Paris is that evening, not the next UTC morning's."""
    from datetime import date

    paris = timezone(timedelta(hours=2))
    assert web_statistics.day_of("2026-09-02T22:30:00.000Z", paris) == date(2026, 9, 3)
    assert web_statistics.day_of("2026-09-02T22:30:00.000Z", timezone.utc) == date(2026, 9, 2)
    assert web_statistics.day_of("2026-09-02", paris) == date(2026, 9, 2)
    assert web_statistics.day_of("", paris) is None
    assert web_statistics.day_of("hier", paris) is None


@case
def a_period_is_thirty_days_unless_it_says_otherwise():
    from datetime import date

    today = date(2026, 9, 29)
    assert web_statistics.period("", "", today) == (date(2026, 8, 31), today)
    assert web_statistics.period("2026-09-01", "2026-09-07", today) == (
        date(2026, 9, 1),
        date(2026, 9, 7),
    )
    for start, end in (("2026-09-07", "2026-09-01"), ("2020-01-01", "2026-01-01"), ("hier", "")):
        try:
            web_statistics.period(start, end, today)
        except ValueError:
            continue
        raise AssertionError(f"{start}..{end} should have been refused")


def _bare_api(client, me: str = "runner-id") -> web_api.Api:
    """An Api with its Notion replaced, and nothing else built."""
    api = web_api.Api.__new__(web_api.Api)
    api._runner = _bare_runner(client)
    api._runner._me = me
    api.hub = web_live.Hub()
    api._config = C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(),
    )
    api._stamp = 0.0
    api._projects = {}
    api._projects_at = 0.0
    api._briefs = {}
    # The pictures kept in a directory of the test's own: the real one is under
    # the state directory of whoever runs the suite.
    pictures = Path(tempfile.mkdtemp())
    api._images = images.Cache(pictures, database=pictures / "ponos.db")
    return api


@case
def a_message_typed_at_a_ticket_is_a_comment_in_your_own_voice():
    """The console writes with the runner's token; the words are still yours.

    Without the relayed opening, the next run would read its own voice under its
    own question — and a conversation with oneself is the one failure mode here
    that never ends on its own.
    """
    report = notion.Comment(
        f"{legacy.OLD}@laptop — blocked.\nWhich header?",
        discussion_id="d-report",
        created_by="runner-id",
    )
    client = _TalkClient([notion.Comment("une note à moi", discussion_id="d-mine"), report])
    api = _bare_api(client)
    api.tell("p-ticket", "  Celui du dashboard.  ")

    page, text, discussion = client.written[0]
    assert page == "p-ticket"
    assert conversation.is_relayed(text), text
    assert conversation.said(text) == "Celui du dashboard."
    assert discussion == "d-report", "an answer goes under the question, not at the foot of the page"

    try:
        api.tell("p-ticket", "   ")
    except ValueError:
        pass
    else:
        raise AssertionError("an empty message should not become a comment")


@case
def a_ticket_the_runner_has_never_spoken_on_gets_a_thread_of_its_own():
    """No question to answer, and none invented: the message opens a discussion."""
    client = _TalkClient([notion.Comment("une remarque", discussion_id="d-mine", created_by="salva")])
    _bare_api(client).tell("p-ticket", "on reprend ça demain")
    assert client.written[0][2] == ""
    # Same when Notion will not say who we are: without an identity there is no
    # telling our own thread from yours, and guessing is how it goes wrong.
    other = _TalkClient([notion.Comment("un rapport", discussion_id="d-report", created_by="runner-id")])
    _bare_api(other, me="").tell("p-ticket", "et celui-ci ?")
    assert other.written[0][2] == ""


@case
def the_discussion_of_a_ticket_reads_as_a_conversation():
    """The ticket's terminal is the page's comments, said by who said them."""
    client = _TalkClient([
        notion.Comment(
            f"{legacy.OLD}@laptop — blocked.\nWhich header?",
            created_time="2026-08-30T10:00:00.000Z",
            discussion_id="d-report",
            created_by="runner-id",
        ),
        notion.Comment(
            f"{conversation.RELAYED[0]}Telegram by Salva.\nCelui du dashboard.",
            discussion_id="d-report",
            created_by="runner-id",
        ),
        notion.Comment("Merci.", discussion_id="d-report", created_by="salva"),
    ])
    payload = _bare_api(client).talk("p-ticket")
    assert [message["role"] for message in payload["messages"]] == ["runner", "you", "you"]
    said = payload["messages"][1]["text"]
    assert said == "Celui du dashboard.", f"the device it came through is not the message: {said}"
    assert payload["mention"] == conversation.MENTION, "the hint has to name what the runner answers to"

    # An integration that will not say who we are still leaves the discussion
    # readable: a report opens with the name the runner signs it with.
    blind = _bare_api(client, me="").talk("p-ticket")
    assert [message["role"] for message in blind["messages"]] == ["runner", "you", "you"]


@case
def a_question_left_unanswered_is_a_ticket_waiting_on_you():
    """The page opens on the discussion when the last word is a run's question."""
    question = notion.Comment(
        f"{voice.MARKS['blocked']} Question\nWhich header?",
        discussion_id="d-report",
        created_by="runner-id",
    )
    assert _bare_api(_TalkClient([question])).talk("p-ticket")["waiting"] is True
    answered = _TalkClient([question, notion.Comment("Celui du dashboard.", discussion_id="d-report", created_by="salva")])
    assert _bare_api(answered).talk("p-ticket")["waiting"] is False, "an answered question waits on nobody"
    report = notion.Comment(f"{voice.MARKS['review']} To review — PR #38", created_by="runner-id")
    assert _bare_api(_TalkClient([report])).talk("p-ticket")["waiting"] is False, "a report is not a question"
    assert _bare_api(_TalkClient([])).talk("p-ticket")["waiting"] is False


@case
def a_message_written_to_a_ticket_reaches_every_open_console():
    """A click posts and says nothing: what appears is what came back on the stream."""
    api = _bare_api(_TalkClient([]))
    channel = api.hub.subscribe(after=0)
    api.tell("p-ticket", "on garde le bandeau")
    event = channel.get_nowait()
    assert event.kind == "talk"
    assert event.payload["ticket"] == "p-ticket"
    assert event.payload["role"] == "you"
    assert event.payload["text"] == "on garde le bandeau"


@case
def a_password_is_masked_and_what_only_talks_of_one_is_left_alone():
    """The sentences `frontend/src/lib/secrets.test.ts` reads, read here too.

    Masked, the label stays and the value goes: the next session still knows
    a password was given, and has to ask for it some other way.
    """
    shown = {
        "mot de passe : hunter2": (["password"], "mot de passe : ••••••"),
        "password=S3cr3t!": (["password"], "password=••••••"),
        "Le mot de passe npm de l'agence est Hz!2026kpl": (
            ["password"], "Le mot de passe npm de l'agence est ••••••",
        ),
        'mdp: "azerty123" merci': (["password"], 'mdp: "••••••" merci'),
        "la clé API : abcd1234": (["password"], "la clé API : ••••••"),
        "voici ghp_abcdefghijklmnopqrstuvwxyz0123456789": (["token"], "voici ••••••"),
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz": (["token"], "••••••"),
        "npm_abcdefghijklmnopqrstuvwxyz0123456789": (["token"], "••••••"),
        "git clone https://salva:p4ss@github.com/x/y.git": (
            ["address"], "git clone https://salva:••••••@github.com/x/y.git",
        ),
        "token : ghp_abcdefghijklmnopqrstuvwxyz0123456789": (["token", "password"], "token : ••••••"),
    }
    for text, (kinds, masked) in shown.items():
        assert redaction.found(text) == kinds, (text, redaction.found(text))
        assert redaction.masked(text) == masked, (text, redaction.masked(text))
    for text in (
        "le token est expiré, refais-le",
        "le secret est dans le coffre",
        "Oui, vas-y avec le mot de passe que tu as.",
        "commit 8df7c20a1b2c3d4e5f60718293a4b5c6d7e8f901, session 3fe451680af4819c8f1bdb25215b6ff7",
        "https://github.com/SalvadorCardona/ticket-runner/pull/284",
    ):
        assert redaction.found(text) == [], text
        assert redaction.masked(text) == text, text


@case
def the_page_and_the_runner_know_the_same_tokens():
    """`secrets.ts` warns about what `redaction` masks: the same list, twice."""
    source = (Path(__file__).resolve().parents[1] / "frontend/src/lib/secrets.ts").read_text()
    listed = re.search(r"export const TOKENS[^\[]*\[(.*?)\n\]", source, re.S)
    assert listed, "secrets.ts lost its TOKENS"
    written = re.findall(r"String\.raw`(.*?)`,", listed.group(1))
    assert written == list(redaction.TOKENS), written


@case
def a_password_typed_at_a_ticket_never_reaches_the_page():
    """Masked before the comment, the stream and the answer all see it."""
    client = _TalkClient([])
    api = _bare_api(client)
    channel = api.hub.subscribe(after=0)
    message = api.tell("p-ticket", "Le mot de passe npm est Hz!2026kpl, publie la 1.2.0")
    written = client.written[0][1]
    assert "Hz!2026kpl" not in written, written
    assert conversation.said(written) == "Le mot de passe npm est ••••••, publie la 1.2.0"
    assert "Hz!2026kpl" not in channel.get_nowait().payload["text"]
    assert "Hz!2026kpl" not in message["text"]

    # A reply from a phone goes the same way.
    relayed = channels.answer(
        channels.Reply(channel="telegram", text="token: npm_abcdefghijklmnopqrstuvwxyz0123456789")
    )
    assert "npm_" not in relayed and relayed.endswith("token: ••••••"), relayed


@case
def a_password_given_with_a_decision_never_reaches_the_page():
    """The instruction typed under a blocked ticket is an answer like any other."""
    settings = C.Notion()
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        api = _ideas_api(board)
        said = api.runner.voice
        page = board.create_row("tickets", "Publish", {"Status": settings.state("blocked")})
        board.update("tickets", page, {"Project": [project]})
        board.comment(page, said.report(said.verdict("blocked", "nothing"), "No npm login."))
        api.decide(page, "other", text="Le mot de passe : Hz!2026kpl")
        comment = board.comments(page)[-1].text
        assert "Hz!2026kpl" not in comment and comment.endswith("Le mot de passe : ••••••"), comment


@case
def the_console_draws_what_comes_back_on_its_own():
    """A schedule the runner reads is one the console shows, problem included.

    And the switch travels with the rows, because a browser is the one place
    `runner.schedule = false` cannot be seen otherwise: a page of ticked
    schedules that never fire would read as a calendar that works.
    """
    import time as clock

    ahead = (datetime.now().astimezone() + timedelta(days=5)).replace(second=0, microsecond=0)
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring(
        [
            _schedule_page(
                "s-1",
                next=ahead.isoformat(),
                last_ticket="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            ),
            _schedule_page("s-2", name="Le rapport", cadence="Fortnightly", active=False),
        ],
        schedule=False,
    )
    api._config = api._runner.config
    api._projects = {"p-animalink": {"id": "panimalink", "name": "Animalink", "kind": "code"}}
    api._projects_at = clock.time()

    payload = api.schedules()
    assert payload["database"], "the workspace has one; the pane must not offer to build it"
    assert payload["page"] == "Schedules"
    assert payload["enabled"] is False, "the one switch that turns the whole calendar off"

    first, second = payload["schedules"]
    assert first["name"] == "Revue des dépendances"
    assert (first["cadence"], first["at"], first["active"]) == ("Daily", "09:00", True)
    assert schedules.scheduled_for(first["next"]) == ahead
    assert first["project"] == "Animalink", "the relation is resolved, as it is on a card"
    assert first["project_id"] == "panimalink", "and the page, for a name not known yet"
    assert first["ticket"] == "aaaaaaaabbbbccccddddeeeeeeeeeeee", "addressed as the board does"
    assert not first["problem"]

    # A cadence nobody knows is stepped over by the pass rather than raised, and
    # says so here rather than showing a date it does not have.
    assert second["problem"], "a schedule the runner cannot read has to say why"
    assert second["next"] == "" and second["active"] is False

    # A projects cache gone cold is not a query the rows wait for: the name is
    # left to the console, which has the page to find it by.
    api._projects = {}
    api.projects = lambda: (_ for _ in ()).throw(AssertionError("the projects were read"))
    first = api.schedules()["schedules"][0]
    assert first["project"] == "" and first["project_id"] == "panimalink"


@case
def a_second_launch_of_the_same_schedule_is_refused_while_the_first_runs():
    """The double click: one ticket, and the second request told why."""
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring([_schedule_page("s-1")])
    api._config = api._runner.config
    api._launching, api._launch_guard = set(), __import__("threading").Lock()
    seen: list[str] = []

    def slow(page_id):
        # The double click lands while the first launch is still writing.
        try:
            api.launch_schedule("s-1")
        except RuntimeError as error:
            seen.append(str(error))
        return {"id": "t1", "ticket": "Revue"}

    api._runner.launch = slow
    assert api.launch_schedule("s-1") == {"ticket": "t1", "title": "Revue"}
    assert seen and "already being launched" in seen[0]
    # And the guard is let go of, so that the next launch is not refused for ever.
    assert api.launch_schedule("s-1")["ticket"] == "t1"


@case
def the_console_never_shows_a_next_occurrence_already_behind_us():
    """`Next` is the pass's bookmark; the list says when a ticket is born.

    Turned off three weeks ago, a schedule keeps the date it had then — and
    nothing will be born from it. Turned on and due, it fires on the very next
    pass, which is now and not a moment in the past.
    """
    stale = "2026-09-09T21:00:00+02:00"
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring(
        [
            _schedule_page("s-1", name="Test email", cadence="Hourly", next=stale,
                           active=False),
            _schedule_page("s-2", cadence="Hourly", next=stale),
        ]
    )
    api._config = api._runner.config
    api._projects = {}
    api.projects = lambda: {"projects": []}

    before = datetime.now().astimezone().replace(second=0, microsecond=0)
    paused, due = api.schedules()["schedules"]
    assert paused["active"] is False and paused["next"] == "", "a paused schedule has no next"
    assert paused["cadence"] == "Hourly", "the word the board holds, translated by the page"
    assert schedules.scheduled_for(due["next"]) >= before, f"an occurrence in the past: {due['next']}"


class _PageClient(_TalkClient):
    """A ticket page: its row, and the blocks written under it."""

    def __init__(self, content: str, status: str = "Ready") -> None:
        super().__init__([])
        self._content = content
        self._status = status

    def page(self, page_id: str) -> notion.Page:
        return notion.Page(
            id="1a2b3c4d-0000-0000-0000-000000000000",
            url="https://notion.so/p",
            title="Retirer le bandeau",
            properties={"Status": {"type": "status", "status": {"name": self._status}}},
            raw={"created_time": "2026-09-01T09:00:00.000Z"},
        )

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._content


@case
def a_ticket_read_on_its_own_is_the_card_and_the_page_under_it():
    """The board hands out rows; the ticket's page hands out what was written on it.

    Same shape as the card — the console draws one component for both — plus
    the page's blocks flattened the way the runner reads them before a run: the
    brief you wrote, and the report a run appended under it.
    """
    api = _bare_api(_PageClient("# Brief\nRetirer le bandeau du dashboard.\n\n- [x] fait"))
    api._runner._workspace = type("W", (), {"projects": ""})()
    payload = api.ticket("1a2b3c4d000000000000000000000000")
    assert payload["id"] == "1a2b3c4d000000000000000000000000", "the id is the one the board uses"
    assert payload["short"] == "00000000", "the short id is the tail, where the entropy is"
    assert payload["title"] == "Retirer le bandeau"
    assert payload["column"] == "ready", "the column is named the way the board names it"
    assert payload["content"].startswith("# Brief"), "the page's blocks come with the row"
    assert "- [x] fait" in payload["content"]

    elsewhere = _bare_api(_PageClient("", status="Parked"))
    elsewhere._runner._workspace = type("W", (), {"projects": ""})()
    assert elsewhere.ticket("1a2b3c4d000000000000000000000000")["column"] == "draft"


class _EditedPageClient(_PageClient):
    """A ticket page that says when it was last edited, and counts its block reads."""

    def __init__(self, content: str, edited: str) -> None:
        super().__init__(content)
        self.edited = edited
        self.reads = 0

    def page(self, page_id: str) -> notion.Page:
        page = super().page(page_id)
        page.raw["last_edited_time"] = self.edited
        return page

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        self.reads += 1
        return self._content


@case
def a_ticket_page_is_read_again_only_when_notion_says_it_changed():
    """Opening a ticket read every block of its page, one to three seconds a time.

    The row is still read each time — it is what says the page moved — and the
    blocks only when its `last_edited_time` did. A read made in the very minute
    of the edit is not kept: Notion counts in minutes, and a second edit in that
    minute would not move the time. A Markdown board is never kept.
    """
    client = _EditedPageClient("first brief", "2026-09-01T09:00:00.000Z")
    api = _bare_api(client)
    api._runner._workspace = type("W", (), {"projects": ""})()
    ticket = "1a2b3c4d000000000000000000000000"
    assert api.ticket(ticket)["content"] == "first brief"
    assert api.ticket(ticket)["content"] == "first brief"
    assert client.reads == 1, "an unchanged page is not read twice"

    client._content, client.edited = "second brief", "2026-09-01T09:30:00.000Z"
    assert api.ticket(ticket)["content"] == "second brief", "an edit is read at the next opening"
    assert client.reads == 2

    # Edited just now: the minute is not over, so nothing is kept.
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    client.edited = now.isoformat().replace("+00:00", ".000Z")
    api.ticket(ticket)
    client._content = "third brief"
    assert api.ticket(ticket)["content"] == "third brief", "an edit in the same minute is still read"

    files = _EditedPageClient("on disk", "2026-09-01T09:00:00.000Z")
    board = _bare_api(files)
    board._runner._workspace = type("W", (), {"projects": ""})()
    board._config.storage = C.Storage(mode="markdown")
    board.ticket(ticket)
    board.ticket(ticket)
    assert files.reads == 2, "a file changed by hand says nothing in its edited time"


@case
def a_relation_is_written_as_notion_spells_it():
    """A ticket created from the console names its project, or it is not one."""
    page = "3ca451680af480ae9443de0b65d9abf8"
    assert notion._encode("relation", page) == {"relation": [{"id": page}]}
    assert notion._encode("relation", [page]) == {"relation": [{"id": page}]}
    assert notion._encode("relation", []) == {"relation": []}



class _ColumnsClient(_TalkClient):
    """A tickets database: three rows, one of them under no known heading."""

    def __init__(self, statuses: list[str]) -> None:
        super().__init__([])
        self._statuses = statuses

    def forget_database(self, database: str) -> None:
        pass

    def query(self, database: str, *args, **kwargs) -> list[notion.Page]:
        return [
            notion.Page(
                id=f"{index:08d}-0000-0000-0000-000000000000",
                url="",
                title=f"ticket {index}",
                properties={"Status": {"type": "status", "status": {"name": status} if status else None}},
                raw={"created_time": "2026-09-01T09:00:00.000Z"},
            )
            for index, status in enumerate(self._statuses)
        ]

    def schema(self, database: str) -> dict[str, str]:
        return {"Name": "title", "Status": "status"}

    def options(self, database: str, prop: str) -> list[str]:
        return ["Ready", "In progress", "In review", "Blocked", "Failed", "Done"]


@case
def a_ticket_under_no_known_status_is_a_draft_and_no_column_is_added_for_it():
    """The board used to draw a "No status" column of its own, after Done.

    A ticket written without a status is a draft, and so is one under a status
    nobody configured: it is never claimed, but dropping it from the board
    would hide exactly the card that needs a look. Both sit in the one column
    the drafts have, on the left — no column is added for them.
    """
    api = _bare_api(_ColumnsClient(["Ready", "", "Parked"]))
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    board = api.board()
    keys = [column["key"] for column in board["columns"]]
    assert keys[0] == "draft" and "other" not in keys, keys
    assert board["columns"][0] == {"key": "draft", "name": ""}, "the console names the drafts, not the board"
    assert [item["column"] for item in board["tickets"]] == ["draft", "draft", "ready"]


class _CancelClient(_ColumnsClient):
    """The same database, offering — or not — a cancelled option."""

    def __init__(self, statuses: list[str], offered: bool) -> None:
        super().__init__(statuses)
        self.offered = offered

    def options(self, database: str, prop: str) -> list[str]:
        return [*super().options(database, prop), *(["Cancelled"] if self.offered else [])]


@case
def a_cancelled_ticket_has_its_column_where_the_board_offers_one():
    """Cancelled closes the row, beside Done — on a board that can say it.

    A Notion board without the option is told rather than written into: no
    gesture is offered, and a move asked anyway is refused in words rather than
    sent to an API that would reject it.
    """
    quiet = type("W", (), {"nudge": lambda self: None})()

    api = _bare_api(_CancelClient(["Ready", "Cancelled", "Done"], offered=True))
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api.watch = quiet
    board = api.board()
    keys = [column["key"] for column in board["columns"]]
    assert keys[-2:] == ["done", "cancelled"], keys
    assert board["cancel"] is True
    assert [item["column"] for item in board["tickets"]] == ["ready", "done", "cancelled"]
    assert api.set_status("1" * 32, "cancelled")["status"] == "Cancelled"

    bare = _bare_api(_CancelClient(["Ready", "Done"], offered=False))
    bare._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    bare._schema_at = time.time()
    bare.watch = quiet
    assert bare.board()["cancel"] is False
    try:
        bare.set_status("1" * 32, "cancelled")
    except ValueError as error:
        assert "no “Cancelled” option" in str(error), error
    else:
        raise AssertionError("a status the board does not offer is refused before it is sent")

    # A board that points cancelled at a status the runner moves tickets
    # through has no cancelled column of its own: a cancelled `ready` is run.
    api._config.notion.status = api._runner.config.notion.status = {"cancelled": "Done"}
    assert api.board()["cancel"] is False


@case
def a_markdown_board_reads_and_writes_the_cancelled_status():
    """A board of files declares every default column, cancelled with them."""
    with _board() as board:
        assert "Cancelled" in board.options("tickets", "Status")
        page = board.create_row("tickets", "Plus besoin", {"Status": "Ready"})
        api = _markdown_api(board)
        api.watch = type("W", (), {"nudge": lambda self: None})()
        api._schema_at = time.time()
        shown = api.board()
        assert shown["cancel"] is True
        assert "cancelled" in [column["key"] for column in shown["columns"]]
        board.update("tickets", page, {"Status": "Cancelled"})
        card = next(item for item in api.board()["tickets"] if item["id"] == page.replace("-", ""))
        assert card["column"] == "cancelled" and card["status"] == "Cancelled"
        assert store.read(board.page(page), "Status") == "Cancelled"


@case
def the_runner_never_runs_a_cancelled_ticket_even_when_named():
    """Not from the ready column, not woken by a comment, not by `run --ticket`."""
    with _board() as board:
        page = board.create_row("tickets", "Abandonné", {"Status": "Cancelled"})
        runner = Runner.__new__(Runner)
        runner._journals = {}
        runner.config = C.Config(
            notion=C.Notion(), runner=C.Runner(), projects={}, path=Path("/nowhere/config.toml"),
            web=C.Web(), storage=C.Storage(mode="markdown", path=board.root),
        )
        runner.client = board
        runner._workspace = board.workspace(runner.config.notion)
        said: list[str] = []
        runner.say = said.append
        assert runner.cancelled_column()
        assert runner.requested(page) == []
        assert said == ["Requested ticket is cancelled — not run: Abandonné"]
        assert page.replace("-", "") not in {
            ticket_module.Ticket(found).id for found in board.query(runner.database, runner._ready_filter())
        }
        assert page.replace("-", "") not in {
            ticket_module.Ticket(found).id for found in board.query(runner.database, runner._woken_filter())
        }
        board.update("tickets", page, {"Status": "Blocked"})
        assert [ticket.title for ticket in runner.requested(page)] == ["Abandonné"]


class _DraftClient(_ColumnsClient):
    """The same database, offering a draft option, and keeping what is created."""

    def __init__(self, statuses: list[str]) -> None:
        super().__init__(statuses)
        self.created: list[tuple[str, dict]] = []

    def options(self, database: str, prop: str) -> list[str]:
        return ["draft", *super().options(database, prop)]

    def create_row(self, database_id, title, values=None):
        self.created.append((title, dict(values or {})))
        return "f" * 32


@case
def a_ticket_with_no_status_is_a_draft_whether_or_not_the_board_names_them():
    """Master Tickets has a `draft` option; the console put those under "No status".

    The drafts are always the first column, and a ticket with no status is one.
    Named in `[notion.status]`, the column is also the option, and "New ticket"
    with its "Draft" button writes it. Left unnamed, a move to the drafts
    clears the status and a new draft is written with none — and one named the
    same as `ready` is the runner's, so never called a draft.
    """
    quiet = type("W", (), {"nudge": lambda self: None})()

    api = _bare_api(_DraftClient(["draft", "Ready", ""]))
    api._config.notion.status = {"draft": "draft"}
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api.watch = quiet
    board = api.board()
    keys = [column["key"] for column in board["columns"]]
    assert keys[0] == "draft" and "other" not in keys, keys
    assert board["columns"][0]["name"] == "draft", "the status a move writes, as Notion spells it"
    assert [item["column"] for item in board["tickets"]] == ["draft", "draft", "ready"]
    api.create_ticket("Écrire l'audit", ready=False)
    api.create_ticket("Lancer l'audit", ready=True)
    assert [values.get("Status") for _, values in api._runner.client.created] == ["draft", "Ready"]
    assert api.set_status("1" * 32, "draft")["status"] == "draft"

    plain = _bare_api(_DraftClient(["draft", "Ready", ""]))
    plain._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    plain._schema_at = time.time()
    plain.watch = quiet
    board = plain.board()
    assert board["columns"][0] == {"key": "draft", "name": ""}
    assert [item["column"] for item in board["tickets"]] == ["draft", "draft", "ready"]
    plain.create_ticket("Écrire l'audit", ready=False)
    assert plain._runner.client.created == [("Écrire l'audit", {})], "no key, no status, as before"
    assert plain.set_status("1" * 32, "draft")["status"] == "", "a move to the drafts clears the status"

    assert C.Notion().state("draft") == "", "nothing is defaulted"
    assert C.Notion(status={"draft": "Ready"}).state("draft") == "Ready"
    assert web_api._draft(C.Notion(status={"draft": "Ready"})) == "", (
        "a draft that is the runner's ready is no draft"
    )


class _UntitledClient(_ColumnsClient):
    """The same database, where nobody wrote a title on any row."""

    def query(self, database: str, *args, **kwargs) -> list[notion.Page]:
        return [
            notion.Page(id=page.id, url=page.url, title="", properties=page.properties, raw=page.raw)
            for page in super().query(database, *args, **kwargs)
        ]


@case
def a_ticket_without_a_title_is_named_by_the_console_in_its_language():
    """"(untitled ticket)" used to come from the server, in English on a French console.

    The server sends the title Notion has — none — and the console says what
    to call it, through the dictionary like every other word it says.
    """
    api = _bare_api(_UntitledClient(["Ready"]))
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    assert [item["title"] for item in api.board()["tickets"]] == [""]
    store_ = (FRONTEND / "src/lib/board-store.ts").read_text(encoding="utf-8")
    assert 't("(untitled ticket)")' in store_, "the console no longer names a ticket without a title"
    french = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    assert '"(untitled ticket)": "(ticket sans titre)"' in french


@case
def the_pages_of_a_list_are_said_in_the_console_s_language():
    """react-resource-view writes "Showing 1 to 30 sur 475 results" whatever the language.

    Every list brings the console's own pagination, whose words go through the
    dictionary, with one ellipsis between the pages rather than four dots.
    """
    pagination = (FRONTEND / "src/components/console/pagination.tsx").read_text(encoding="utf-8")
    assert 't("Showing {{from}} to {{to}} of {{total}} results"' in pagination
    assert "…" in pagination and "...." not in pagination
    french = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    assert '"Affichage de {{from}} à {{to}} sur {{total}} résultats"' in french
    # Given once, under every resource, rather than list by list.
    views = (FRONTEND / "src/lib/resource-view.ts").read_text(encoding="utf-8")
    assert "defaults: { components: { pagination: Pagination } }" in views, (
        "the lists say their pages in English"
    )
    for resource in ("tickets", "projects", "schedules", "pairs"):
        source = (FRONTEND / f"src/resources/{resource}.tsx").read_text(encoding="utf-8")
        assert "pagination: null" not in source, f"the {resource} list says its pages in English"


def _session_line(kind: str = "assistant") -> str:
    if kind == "result":
        return json.dumps({"type": "result", "result": "done", "session_id": "s"}) + "\n"
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "reading"}]}}
    ) + "\n"


@case
def a_session_is_running_until_its_log_says_its_last_word():
    """A step says a session is alive; only the `result` line says it is over.

    Counted from the logs rather than from the steps a browser happened to see:
    a console reloaded mid-run counted nothing, and one left open counted every
    session it had ever seen as still writing.
    """
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        working = folder / "20260830-120000-1a2b3c4d.jsonl"
        working.write_text(_session_line(), encoding="utf-8")
        finished = folder / "20260830-110000-9f8e7d6c.jsonl"
        finished.write_text(_session_line() + _session_line("result"), encoding="utf-8")

        running = web_live.active(folder, held=lambda: "4242 now")
        assert running == [{"source": "1a2b3c4d", "log": working.name}], running
        assert web_live.active(folder, held=lambda: "") == [], (
            "no run holds the lock: a log that still looks fresh is a run that died"
        )

        # An answer longer than what is read of the end is still recognised.
        huge = folder / "20260830-130000-00aa11bb.jsonl"
        huge.write_text(
            _session_line()
            + json.dumps({"type": "result", "result": "x" * (web_live.ENDING_BYTES + 10)})
            + "\n",
            encoding="utf-8",
        )
        assert web_live.answered(huge)


@case
def how_long_a_session_took_is_read_from_its_log_where_the_board_has_no_column():
    """The `result` line carries the duration; a run still writing does not count."""
    finished = json.dumps({"type": "result", "result": "done", "duration_ms": 540_000}) + "\n"
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        assert web_live.lasted("1a2b3c4d", folder) is None, "no log, no duration"
        (folder / "20260830-110000-1a2b3c4d.jsonl").write_text(
            _session_line() + finished, encoding="utf-8"
        )
        (folder / "20260830-120000-1a2b3c4d.jsonl").write_text(_session_line(), encoding="utf-8")
        (folder / "20260830-130000-1a2b3c4d-talk.jsonl").write_text(
            _session_line() + json.dumps({"type": "result", "duration_ms": 60_000}) + "\n",
            encoding="utf-8",
        )
        assert web_live.lasted("1a2b3c4d", folder) == 9.0, (
            "the newest finished session of the ticket — not a run in progress, not a reply"
        )
        assert web_live.lasted("9f8e7d6c", folder) is None


@case
def the_sessions_running_are_announced_when_they_change_and_kept_for_the_next_tab():
    hub = web_live.Hub()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        log = folder / "20260830-120000-1a2b3c4d.jsonl"
        log.write_text(_session_line(), encoding="utf-8")
        tail = web_live.Tail(hub, folder, held=lambda: "4242")
        said = []
        publish = hub.publish

        def listening(kind: str, **payload: object) -> None:
            said.append((kind, payload))
            publish(kind, **payload)

        hub.publish = listening  # type: ignore[method-assign]
        tail.pass_once()
        tail.pass_once()
        announced = [payload for kind, payload in said if kind == "sessions"]
        assert announced == [{"sessions": [{"source": "1a2b3c4d", "log": log.name}]}], (
            "said once, and not again while nothing changed"
        )

        # A tab opened now is told what is running before anything else moves.
        fresh = hub.subscribe()
        kinds = [fresh.get_nowait().kind for _ in range(fresh.qsize())]
        assert kinds == ["sessions"], kinds

        with log.open("a", encoding="utf-8") as handle:
            handle.write(_session_line("result"))
        tail.pass_once()
        announced = [payload for kind, payload in said if kind == "sessions"]
        assert announced[-1] == {"sessions": []}, "the end of a session is news too"


@case
def the_pages_before_the_console_speak_the_browsers_language():
    """The sign-in and the gate, as the console would say them.

    Same rule as the console: the browser's own list decides. And every field
    has a label that names it, rather than a greyed example that vanishes the
    moment somebody starts typing.
    """
    from ponos.web import server as web_server

    assert web_server.language_of("fr-FR,fr;q=0.9,en;q=0.8") == "fr"
    assert web_server.language_of("de-DE,en-GB;q=0.7") == "en"
    assert web_server.language_of("") == "en"

    for build in (web_server.sign_in_page, web_server.gate_page):
        french = build("fr")
        assert '<html lang="fr"' in french
        assert "Ouvrir la console" in french
        assert web_server.GUARD_HEADER in french or build is web_server.gate_page
        for field in re.findall(r'<(?:input|textarea)[^>]*\bid="([^"]+)"', french):
            assert f'<label for="{field}"' in french, f"{field} has no label"
        assert "#3b82f6" not in french, "the door is drawn in the console's own blue, not a stock one"
    assert '<html lang="en"' in web_server.SIGN_IN


@case
def the_gate_says_where_this_machines_token_actually_is():
    """`~/.local/state/…` printed as a constant was wrong wherever XDG_STATE_HOME is set."""
    from ponos.web import server as web_server

    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = "/srv/elsewhere"
    try:
        page = web_server.gate_page("en")
    finally:
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous
    assert "/srv/elsewhere/ponos/web/token" in page
    assert "~/.local/state" not in page


@case
def the_gate_says_a_chosen_token_lives_in_secrets_env_and_why_a_cookie_was_refused():
    """The token left `config.toml` for `secrets.env`; the gate said otherwise.

    And a cookie is scoped by host, not by port: a test console beside 8787
    overwrites 8787's, and the gate came back with nothing to say why.
    """
    import urllib.error
    import urllib.request

    from ponos.web import server as web_server

    api = _bare_api(_TalkClient([]))
    api._config.web.token = "tok"
    folder = Path(tempfile.mkdtemp())
    api._config.path = folder / "config.toml"
    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def gate(path: str, cookie: str = "") -> str:
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        request.add_header("Accept-Language", "fr")
        if cookie:
            request.add_header("Cookie", f"{web_server.COOKIE}={cookie}")
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 401
            return error.read().decode()
        raise AssertionError("the door opened")

    previous = os.environ.pop(C.SECRETS_PATH_ENV, None)
    try:
        page = gate("/")
        assert "variable d'environnement <code>PONOS_WEB_TOKEN</code>" in page, page
        assert "web.token" not in page
        assert "n'est pas celui de cette console" not in page, "nothing was offered"

        (folder / "secrets.env").write_text("PONOS_WEB_TOKEN=tok\n")
        page = gate("/", cookie="another-consoles")
        assert f"<code>{folder / 'secrets.env'}</code>" in page, page
        assert "n'est pas celui de cette console" in page
        assert "jeton incorrect" in gate("/?token=nope")
    finally:
        if previous is not None:
            os.environ[C.SECRETS_PATH_ENV] = previous
        console.shutdown()
        console.server_close()


@case
def the_door_is_drawn_in_the_consoles_palette_in_both_themes():
    """Hermez's stone and orange, dark unless the console was switched to light."""
    from ponos.web import server as web_server

    tokens = (ROOT / "frontend" / "src" / "tokens.css").read_text()
    light, dark = tokens.split("\n.dark {", 1)
    for name in ("background", "card", "primary", "field", "foreground"):
        ours = re.findall(rf"--{name}:([^;]+);", web_server._STYLE)
        assert ours[0] in light.replace("#ffffff", "#fff"), name
        assert ours[1] in dark, name
    assert '<html lang="en" class="dark">' in web_server.GATE
    assert "ponos-theme" in web_server.GATE, "the choice made in the console is the door's too"


@case
def a_write_refused_before_its_body_is_read_closes_the_connection():
    """A POST turned away unread must not leave its body on a reused connection.

    The browser reuses a keep-alive connection: the `{}` of a refused
    `/api/refresh` was read as the start of the next request, and a signed-out
    page that reloaded itself got "501 Unsupported method ('{}GET')" instead of
    the sign-in.
    """
    import socket as sockets

    from ponos.web import server as web_server

    api = _bare_api(_TalkClient([]))
    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
    thread = threading.Thread(target=console.serve_forever, daemon=True)
    thread.start()
    try:
        port = console.server_address[1]
        with sockets.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(
                b"POST /api/refresh HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Ponos: 1\r\n"
                b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
                b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
            )
            answer = b""
            while chunk := connection.recv(65536):
                answer += chunk
    finally:
        console.shutdown()
        console.server_close()
    said = answer.decode("utf-8", "replace")
    assert said.startswith("HTTP/1.1 401"), said[:80]
    assert "Connection: close" in said
    assert "501" not in said, "the body was read as the next request"


@case
def a_client_that_hangs_up_mid_answer_leaves_no_trace():
    """A tab closed while its board was on the way is not an error.

    The journal of `ponos-web.service` held 38 tracebacks by 1 October
    2026, two per closed tab: the `BrokenPipeError` of the write, then the 500
    the route's `except Exception` tried to send on the same dead socket.
    """
    import io
    import socket as sockets

    from ponos.web import server as web_server

    done = threading.Event()

    class Handler(web_server.Handler):
        def finish(self) -> None:
            try:
                super().finish()
            finally:
                done.set()

    api = _bare_api(_TalkClient([]))
    console = web_server.Console(("127.0.0.1", 0), Handler, api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]
    request = (
        b"GET /api/board HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer tok\r\n\r\n"
    )
    stderr, sys.stderr = sys.stderr, io.StringIO()
    try:
        # Far more than the socket buffers hold, so the write meets the hang-up.
        api.board = lambda: {"tickets": ["x" * 1024] * 8192}
        with sockets.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(request)
            connection.recv(100)
        assert done.wait(5), "the request never finished"
        journal = sys.stderr.getvalue()

        def broken():
            raise RuntimeError("the board is upside down\nand more")

        api.board = broken
        done.clear()
        with sockets.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(request.replace(b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n"))
            answer = b""
            while chunk := connection.recv(65536):
                answer += chunk
    finally:
        sys.stderr = stderr
        console.shutdown()
        console.server_close()
    assert journal == "", journal
    said = answer.decode("utf-8", "replace")
    assert said.startswith("HTTP/1.1 500"), said[:80]
    assert said.endswith('{"error": "the board is upside down"}'), said[-80:]


@case
def a_path_field_picks_from_the_folder_it_points_at():
    """Names, folders first; a file typed half-way lists its folder."""
    root = Path(tempfile.mkdtemp())
    (root / "prompts").mkdir()
    (root / "ticket.md").write_text("x", encoding="utf-8")
    (root / ".hidden").write_text("x", encoding="utf-8")
    listed = web_settings.folder(str(root))
    assert listed["folder"] == str(root) and listed["parent"] == str(root.parent)
    assert listed["entries"] == [
        {"name": "prompts", "folder": True},
        {"name": "ticket.md", "folder": False},
    ], "hidden ones stay hidden"
    assert web_settings.folder(str(root / "tic"))["folder"] == str(root)
    assert any(item["name"] == ".hidden" for item in web_settings.folder(str(root / ".h"))["entries"])


@case
def an_example_token_is_not_a_token_the_settings_call_set():
    """The `ntn_xxxx…` the example file ships with is where a token goes, not one."""
    assert web_settings._preview(C.PLACEHOLDER) == ""
    assert web_settings._preview("ntn_xxxxxxxx") == ""
    assert web_settings._preview("ntn_real_secret_abcd") == "…abcd"


@case
def the_settings_are_six_pages_and_every_key_is_on_one_of_them_once():
    """Grouped by the question somebody asks, not by the table the loader reads.

    Twenty-two sections at one rank put the Notion token beside the twenty-one
    names of its properties. Six pages now, the names folded at the end of the
    one about where tickets come from — and every model the runner can be told
    to use on the page about models, rather than wherever its table was.
    """
    groups = [group.key for group in web_settings.GROUPS]
    assert len(groups) == 6 and len(set(groups)) == 6, groups
    for section in web_settings.SECTIONS:
        assert section.group in groups, f"{section.key} is on no page"
        assert not section.fold or section.fold in web_settings.FOLDS, section.key
    assert {section.group for section in web_settings.SECTIONS} == set(groups), "an empty page"

    names = [field.name for section in web_settings.SECTIONS for field in section.fields]
    twice = sorted({name for name in names if names.count(name) > 1})
    assert not twice, f"drawn on two cards: {twice}"
    keys = [section.key for section in web_settings.SECTIONS]
    assert len(keys) == len(set(keys)), "two cards under one key"

    where = {
        field.name: section
        for section in web_settings.SECTIONS
        for field in section.fields
    }
    for name in where:
        if not name.startswith("notion.") and "model" in name.rpartition(".")[2]:
            assert where[name].group == "models", f"{name} is not with the models"
    for table in ("status", "properties", "pages", "types"):
        for key in C.defaults(table):
            assert where[f"notion.{table}.{key}"].fold == "mapping", f"notion.{table}.{key}"
    notion = [name for name in where if name.startswith("notion.") and not where[name].fold]
    assert sorted(notion) == ["notion.mention", "notion.tickets_database", "notion.token",
                              "notion.workspace"], notion
    assert where["notion.mention"].key == "replies", "the word that asks is about answers"
    source = [section.key for section in web_settings.SECTIONS if section.group == "source"]
    assert source.index("storage") < source.index("notion"), "a board need not be in Notion"

    path, config = _saved()
    drawn = web_settings.describe(config)
    assert [group["key"] for group in drawn["groups"]] == groups
    assert drawn["folds"][0]["key"] == "mapping"
    assert {section["group"] for section in drawn["sections"]} == set(groups)


@case
def the_old_desktop_switch_is_one_field_and_moves_when_touched():
    """`runner.notify` and `notify.desktop` said the same thing in two places.

    The page draws the second only, which already falls back on the first; a
    save of it takes the old line away, so the file ends up saying it once —
    and a file nobody touches keeps working as it did.
    """
    assert "runner.notify" not in web_settings.FIELDS
    assert web_settings.LEGACY["runner.notify"] in web_settings.FIELDS
    path, config = _saved('\n[runner]\nnotify = false\n')
    drawn = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert drawn["notify.desktop"]["fallback"] is False, "the old key still answers"
    web_settings.save(config, {"settings": {"notify.desktop": True}})
    text = path.read_text()
    assert "notify = false" not in text and "desktop = true" in text, text
    assert C.load(path).notify.desktop is True


@case
def a_value_the_environment_gives_is_said_to_come_from_it():
    """Retyping a token the environment overrides changes nothing — the page says so."""
    path, config = _saved()
    with _environment(PONOS_SLACK_TOKEN="xoxb-from-the-environment", PONOS_WEB_EMAIL="me@example.com"):
        drawn = {
            field["name"]: field
            for section in web_settings.describe(config)["sections"]
            for field in section["fields"]
        }
    assert drawn["notify.slack.token"]["environment"] == "PONOS_SLACK_TOKEN"
    assert drawn["web.email"]["environment"] == "PONOS_WEB_EMAIL"
    assert drawn["notion.token"]["environment"] == "", "secrets.env holds this one"


@case
def a_container_is_given_its_language_by_the_environment():
    """`PONOS_LANGUAGE` when the file names none; the file when it does."""
    path, _ = _saved()
    with _environment(PONOS_LANGUAGE="fr"):
        assert C.load(path).runner.language == "fr"
        assert C.load(path).runner.interface_language() == "fr", "the console follows it too"
    with _environment(PONOS_LANGUAGE=None):
        assert C.load(path).runner.language == "", "nothing said is still nothing said"
    path, _ = _saved('\n[runner]\nlanguage = "en"\n')
    with _environment(PONOS_LANGUAGE="fr"):
        assert C.load(path).runner.language == "en", "a language picked in Settings wins"


# -- the settings tab ---------------------------------------------------------


def _saved(body: str = "") -> tuple[Path, C.Config]:
    """A configuration file on disk, and the runner's reading of it."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        "# a file somebody wrote by hand\n"
        '[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n' + body,
        encoding="utf-8",
    )
    C.move_secrets(path)  # as a launch leaves it, see `_config`
    return path, C.load(path)


@case
def a_value_is_written_as_toml_spells_it():
    """Four shapes, and a string that would otherwise end the line early."""
    assert C._literal(True) == "true" and C._literal(False) == "false"
    assert C._literal(1800) == "1800"
    assert C._literal(["blocked", "done"]) == '["blocked", "done"]'
    assert C._literal('a "quoted" \\ path') == '"a \\"quoted\\" \\\\ path"'

    path, _ = _saved()
    assert C.write_value(path, "runner", "dry_run", True)
    assert C.write_value(path, "runner", "interval_seconds", 900)
    assert C.write_value(path, "notify", "events", ["blocked"])
    # A project called "Site vitrine" is not a bare key, and has to survive
    # being written and read back under the same name.
    assert C.write_value(path, "projects", "Site vitrine", "~/work/site")
    config = C.load(path)
    assert config.runner.dry_run is True
    assert config.runner.interval_seconds == 900
    assert config.notify.events == ("blocked",)
    assert "Site vitrine" in config.projects
    assert C.write_value(path, "projects", "Site vitrine", "~/work/site") is False


@case
def clearing_a_field_removes_the_line_rather_than_emptying_it():
    """A key the file does not carry is a key the loader answers itself.

    Which is the whole grammar of the settings tab: blank means "say nothing",
    and the default comes back — comments and all, for the next time it is set.
    """
    path, _ = _saved('\n[runner]\n# how often it looks\nmodel = "opus"\ninterval_seconds = 60\n')
    assert C.write_value(path, "runner", "model", None) is True
    assert C.write_value(path, "runner", "model", None) is False, "already gone"
    text = path.read_text()
    assert "model" not in text
    assert "# how often it looks" in text, "the comments around it survive"
    assert C.load(path).runner.model == "", "and the default answers"


@case
def a_save_is_all_of_it_or_none_of_it():
    """Half a configuration is a runner that claims tickets it cannot finish."""
    path, config = _saved('\n[runner]\ninterval_seconds = 900\n')
    before = path.read_text()
    try:
        web_settings.save(
            config,
            {"settings": {"runner.max_concurrent": 4, "runner.merge_method": "fast-forward"}},
        )
    except ValueError as error:
        assert "squash" in str(error), error
    else:
        raise AssertionError("a merge method gh would refuse must not be saved")
    assert path.read_text() == before, "the good half must not have landed either"
    assert not [
        item for item in path.parent.iterdir() if item.name not in ("config.toml", "secrets.env")
    ]


@case
def a_floor_the_loader_would_repair_quietly_is_refused_here():
    """The loader raises a zero interval to one. A form that did so would lie."""
    path, config = _saved()
    for name, value in (
        ("runner.interval_seconds", 0),
        ("runner.progress_interval_seconds", 1),
        ("web.poll_seconds", 2),
        ("runner.update_interval_seconds", 30),
    ):
        try:
            web_settings.save(config, {"settings": {name: value}})
        except ValueError as error:
            assert "at the least" in str(error), error
            continue
        raise AssertionError(f"{name} = {value} should have been refused")


@case
def a_save_that_would_leave_it_unusable_is_refused():
    """The copy is loaded before it is allowed to take the file's place."""
    path, config = _saved()
    before = path.read_text()
    try:
        web_settings.save(config, {"settings": {"notion.token": None}})
    except C.ConfigError as error:
        assert "unusable" in str(error)
        assert ".saving" not in str(error), "and names the file, not the copy"
    else:
        raise AssertionError("a configuration with no token must not be saved")
    assert path.read_text() == before


@case
def a_token_is_never_sent_to_the_browser():
    """A secret goes out as "set, ending in …abcd", and comes back only typed."""
    path, config = _saved(
        '\n[notify.slack]\ntoken = "xoxb-1234567890wxyz"\nchannel = "C1"\n'
    )
    drawn = json.dumps(web_settings.describe(config), ensure_ascii=False)
    assert "ntn_real" not in drawn and "xoxb-1234567890wxyz" not in drawn
    assert "…wxyz" in drawn, "enough to recognise it by"

    fields = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert fields["notify.slack.token"]["stated"] is True
    assert fields["notify.slack.token"]["fallback"] == "", "a secret has no default to show"
    assert fields["notify.telegram.token"]["stated"] is False
    assert fields["notify.telegram.token"]["preview"] == ""
    # Typing one sets it; the gesture that clears one is its own.
    web_settings.save(config, {"settings": {"notify.slack.token": "xoxb-new"}})
    assert C.load(path).notify.slack["token"] == "xoxb-new"
    web_settings.save(C.load(path), {"settings": {"notify.slack.token": None}})
    assert "token" not in C.load(path).notify.slack


@case
def what_the_file_says_is_told_apart_from_what_it_falls_back_on():
    """Otherwise a save would write every default into the file it read."""
    path, config = _saved("\n[runner]\ninterval_seconds = 900\n")
    fields = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    stated = fields["runner.interval_seconds"]
    assert stated["value"] == 900 and stated["stated"] is True
    silent = fields["runner.max_concurrent"]
    assert silent["value"] is None and silent["stated"] is False
    assert silent["fallback"] == C.Runner().max_concurrent, "the default, shown greyed"
    # The three naming tables are drawn from the defaults, not listed twice.
    assert fields["notion.status.validated"]["fallback"] == "Validated"
    assert fields["notion.properties.progress"]["fallback"] == "Progress"


@case
def every_setting_the_file_holds_is_one_the_console_can_reach():
    """A key added to config.py and not described is a key nobody can set.

    The console draws itself from `settings.SECTIONS`; this is what keeps that
    description from falling behind the dataclasses it describes.
    """
    expected = set()
    for table, holder in (
        ("runner", C.Runner()),
        ("web", C.Web()),
        ("notify", C.Notify()),
        ("openrouter", C.OpenRouter()),
        ("claude", C.Claude()),
        ("storage", C.Storage()),
        ("permissions", C.Permissions()),
    ):
        for name in vars(holder):
            # The two channel tables are their own sections, and `projects` is a
            # mapping you add rows to rather than a list of known keys.
            if name in ("telegram", "slack"):
                continue
            expected.add(f"{table}.{name}")
    for name in vars(C.Notion()):
        if name in ("pages", "properties", "status", "types"):
            continue
        expected.add(f"notion.{name}")
    for table in ("pages", "properties", "status", "types"):
        expected |= {f"notion.{table}.{key}" for key in C.defaults(table)}
    # The one naming key with no default: a board names its drafts or has none.
    expected.add("notion.status.draft")
    expected |= {"notify.telegram.token", "notify.telegram.chat"}
    expected |= {"notify.slack.token", "notify.slack.channel"}

    # A mapping the file writes one key per sub-type: see `Runner.auto_model_subtypes`.
    expected.discard("runner.auto_model_subtypes")
    expected |= {f"runner.auto_model_subtype_{key}" for key in subtypes.KEYS}
    # A key the page draws under its newer name instead: see `LEGACY`.
    expected -= set(web_settings.LEGACY)
    missing = expected - set(web_settings.FIELDS)
    assert not missing, f"not reachable from the console: {sorted(missing)}"
    unknown = set(web_settings.FIELDS) - expected
    assert not unknown, f"described but not read by the loader: {sorted(unknown)}"

    for name, field in web_settings.FIELDS.items():
        assert field.label, name
        assert field.kind in ("text", "secret", "path", "bool", "int", "choice", "events", "lines"), name
        if field.kind == "choice":
            assert field.choices, name


@case
def a_choice_is_shown_in_words_and_saved_as_the_file_spells_it():
    """The page says "One commit (squash)"; the file keeps saying `squash`.

    Every value a choice offers has its words, and no words name a value the
    loader would refuse. A section never folds all of itself away: the advanced
    fields sit under the ones somebody setting up a board needs first.
    """
    for name, field in web_settings.FIELDS.items():
        if field.options:
            assert [value for value, _ in field.options] == list(field.choices), name
    path, config = _saved()
    drawn = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert drawn["runner.merge_method"]["options"]["squash"] == "One commit (squash)"
    assert drawn["runner.branch_prefix"]["advanced"] is True
    assert drawn["runner.max_concurrent"]["advanced"] is False
    web_settings.save(config, {"settings": {"runner.merge_method": "rebase"}})
    assert 'merge_method = "rebase"' in path.read_text()
    for section in web_settings.SECTIONS:
        if section.fields:
            assert not all(field.advanced for field in section.fields), section.key


@case
def the_tables_that_are_mappings_gain_and_lose_rows():
    """The two sections that are a mapping rather than a list of known keys.

    `[projects]` and `[github]` are saved by what the browser sends in full, so
    a row you removed there is a line that goes away here.
    """
    path, config = _saved(
        '\n[projects]\n"Site vitrine" = "~/work/site"\nold = "~/work/old"\n'
        '\n[github]\nanimalink = "dev-animalink"\nold = "nobody"\n'
    )
    web_settings.save(
        config,
        {
            "projects": [
                {"name": "Site vitrine", "value": "~/work/site-v2"},
                {"name": "Trader IA", "value": "~/work/trader"},
            ],
            "github": [{"name": "Animalink", "value": "dev-animalink"}],
        },
    )
    saved = C.load(path)
    assert set(saved.projects) == {"Site vitrine", "Trader IA"}, "the row you removed is gone"
    assert saved.projects["Site vitrine"].endswith("site-v2")
    assert saved.github == {"animalink": "dev-animalink"}, "and an owner is read lowercased"

    drawn = web_settings.describe(C.load(path))
    assert {"name": "Animalink", "value": "dev-animalink"} in drawn["github"]
    assert any(section["pairs"] == "github" for section in drawn["sections"])


@case
def a_setting_that_needs_more_than_saving_says_so_and_only_when_it_moved():
    """A notice about a restart you do not need is a notice you stop reading."""
    path, config = _saved()
    result = web_settings.save(config, {"settings": {"runner.interval_seconds": 600}})
    assert result["saved"] == ["runner.interval_seconds"]
    assert any("timer" in note for note in result["after"])

    result = web_settings.save(C.load(path), {"settings": {"runner.max_concurrent": 3}})
    assert result["after"] == [], "nothing to do but the next run"
    # Saving what the file already says changes nothing and claims nothing.
    assert web_settings.save(C.load(path), {"settings": {"runner.max_concurrent": 3}})["saved"] == []


# -- being told, and answering ------------------------------------------------


@contextmanager
def _state():
    """A state directory of its own, so a test never reads yesterday's cursor."""
    previous = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_STATE_HOME"] = directory
        try:
            yield Path(directory)
        finally:
            if previous is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = previous


@contextmanager
def _api(module, answers: dict):
    """Replace one channel's HTTP call with a table of canned answers."""
    calls: list[tuple[str, dict | None]] = []

    def fake(url, payload=None, headers=None):
        calls.append((url, payload))
        for fragment, body in answers.items():
            if fragment in url:
                return body
        return {"ok": True, "result": {}}

    original = module.request
    module.request = fake
    try:
        yield calls
    finally:
        module.request = original


@case
def a_word_is_a_verdict_only_when_it_opens_the_sentence():
    assert channels.decide("oui") == "yes"
    assert channels.decide("Yes, and rename the column while you are there") == "yes"
    assert channels.decide("👍") == "yes"
    assert channels.decide("non") == "no"
    assert channels.decide("No — that column stays") == "no"
    assert channels.decide("aucune idée, demande à Marie") == "", "not every sentence is a verdict"
    assert channels.decide("I have no idea") == "", "a no in the middle is not an answer"
    assert channels.decide("   ") == ""


@case
def a_bare_yes_reaches_the_agent_as_a_sentence():
    """"oui" means nothing to a session that never saw the notification."""
    written = channels.answer(channels.Reply(channel="telegram", text="oui", who="Salvador"))
    assert "Salvador" in written
    assert "go ahead" in written
    assert written.count("oui") == 0, "the word itself adds nothing once it is spelled out"

    kept = channels.answer(
        channels.Reply(channel="slack", text="oui, et renomme la colonne aussi")
    )
    assert "go ahead" in kept
    assert "renomme la colonne" in kept, "what was said around the word is the instruction"

    free = channels.answer(channels.Reply(channel="telegram", text="celui du dashboard"))
    assert "celui du dashboard" in free
    assert "go ahead" not in free and "do not" not in free


TICKET = "3ca451680af480ae9443de0b65d9abf8"
OTHER = "3ca451680af480beb02ac9d2cb79078c"


def _asks() -> list[channels.Ask]:
    return [
        channels.Ask(ref="10", ticket=OTHER, title="Le footer"),
        channels.Ask(ref="11", ticket=TICKET, title="Le header"),
    ]


@case
def an_answer_finds_its_ticket_by_thread_first_then_by_name():
    channel = telegram_channel.Telegram("token", "42")
    replied = channel._route(channels.Incoming(ref="12", thread="10", text="oui"), _asks())
    assert replied.ticket == OTHER, "a reply to a message answers that message"

    named = channel._route(
        channels.Incoming(ref="12", text="oui pour 3ca45168-0af4-80be-b02a-c9d2cb79078c"),
        _asks(),
    )
    assert named.ticket == OTHER, "a ticket named in the text is not a guess either"

    last = channel._route(channels.Incoming(ref="12", text="oui"), _asks())
    assert last.ticket == TICKET, "a bare yes answers the question just asked"
    assert channel._route(channels.Incoming(ref="12", text="oui"), []) is None


@case
def a_telegram_message_from_anywhere_else_is_not_an_answer():
    """A bot token is a public address: anyone can write to it."""
    channel = telegram_channel.Telegram("token", "42")
    updates = {
        "ok": True,
        "result": [
            {"update_id": 7, "message": {"message_id": 1, "chat": {"id": 42},
                                         "from": {"first_name": "Salvador"}, "text": "oui"}},
            {"update_id": 8, "message": {"message_id": 2, "chat": {"id": 99},
                                         "from": {"first_name": "Someone"}, "text": "rm -rf"}},
            {"update_id": 9, "message": {"message_id": 3, "chat": {"id": 42},
                                         "from": {"is_bot": True}, "text": "echo"}},
        ],
    }
    with _api(telegram_channel, {"getUpdates": updates}) as calls:
        incoming, cursor = channel._fetch("", [])
    assert [message.text for message in incoming] == ["oui"]
    assert incoming[0].who == "Salvador"
    assert cursor == "10", "the offset acknowledges what was read, so it is read once"
    assert calls[0][1]["allowed_updates"] == ["message"]


@case
def in_a_group_only_the_people_named_may_answer():
    """An answer becomes a comment, and a comment wakes a ticket whose session
    runs with `bypassPermissions`. In a group, "can write here" was "can run
    commands on the machine"; `allowed_users` names who may."""
    group = {
        "ok": True,
        "result": [
            {"update_id": 7, "message": {"message_id": 1, "chat": {"id": -42},
                                         "from": {"id": 1001, "first_name": "Salvador"},
                                         "text": "oui"}},
            {"update_id": 8, "message": {"message_id": 2, "chat": {"id": -42},
                                         "from": {"id": 2002, "first_name": "Someone"},
                                         "text": "et supprime la base"}},
        ],
    }
    with _api(telegram_channel, {"getUpdates": group}):
        everybody, _ = telegram_channel.Telegram("token", "-42")._fetch("", [])
    assert [message.text for message in everybody] == ["oui", "et supprime la base"], (
        "nobody named is the old behaviour, kept"
    )
    with _api(telegram_channel, {"getUpdates": group}):
        named, cursor = telegram_channel.Telegram("token", "-42", frozenset({"1001"}))._fetch("", [])
    assert [message.who for message in named] == ["Salvador"], named
    assert cursor == "9", "what was dropped is still acknowledged, so it is never read again"

    channel = slack_channel.Slack("xoxb-token", "C1", frozenset({"U1"}))
    assert channel._read({"ts": "2", "user": "U1", "text": "oui"}, "1").text == "oui"
    assert channel._read({"ts": "3", "user": "U2", "text": "rm -rf"}, "1") is None
    assert slack_channel.Slack("xoxb", "C1")._read({"ts": "3", "user": "U2", "text": "ok"}, "1")

    config = _config(
        '[notify.telegram]\ntoken = "123:abc"\nchat = "-42"\nallowed_users = [1001, 1002]\n'
        '[notify.slack]\ntoken = "xoxb-1"\nchannel = "C1"\nallowed_users = "U1, U2"\n'
    )
    opened = {channel.name: channel.allowed for channel in channels.open(config.notify)}
    assert opened == {"telegram": {"1001", "1002"}, "slack": {"U1", "U2"}}, opened
    assert channels.allowed_users("") == frozenset()


def _update(identifier: int, message: int, text: str) -> dict:
    return {
        "update_id": identifier,
        "message": {
            "message_id": message,
            "chat": {"id": 42},
            "from": {"first_name": "Salvador"},
            "text": text,
        },
    }


SENT = {"sendMessage": {"ok": True, "result": {"message_id": 5}}}


@case
def nothing_said_before_the_runner_was_listening_is_an_answer():
    """Telegram keeps a day of updates; Slack keeps everything ever said."""
    channel = telegram_channel.Telegram("token", "42")
    backlog = {"ok": True, "result": [_update(7, 1, "oui"), _update(8, 2, "et le footer ?")]}
    with _state():
        with _api(telegram_channel, {"getUpdates": backlog, **SENT}):
            channel.send("?", ticket=TICKET, title="Le header", ask=True)
            assert channel.collect() == [], "a backlog is a conversation, not a queue"
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": [_update(9, 3, "oui")]}}) as calls:
            assert [reply.text for reply in channel.collect()] == ["oui"]
            assert calls[0][1]["offset"] == 9, "the first poll only settled where now is"


@case
def what_a_channel_reads_once_it_never_reads_again():
    channel = telegram_channel.Telegram("token", "42")
    with _state():
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": []}, **SENT}):
            channel.send("Blocked · le header ?", ticket=TICKET, title="Le header", ask=True)
            assert channel.collect() == []
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": [_update(7, 1, "oui")]}}):
            first = channel.collect()
        assert [reply.ticket for reply in first] == [TICKET]
        assert first[0].title == "Le header", "the question remembers what it was about"
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": []}}) as calls:
            assert channel.collect() == []
            assert calls[0][1]["offset"] == 8, "resumed where the last run stopped"


@case
def a_room_shared_with_other_people_never_guesses():
    """In Slack the message beside yours belongs to somebody else's thread."""
    ask = [channels.Ask(ref="100.0", ticket=TICKET, title="Le header")]
    loose = channels.Incoming(ref="100.4", text="ok")
    assert slack_channel.Slack("xoxb", "C1")._route(loose, ask) is None
    assert telegram_channel.Telegram("token", "42")._route(loose, ask).ticket == TICKET
    threaded = channels.Incoming(ref="100.4", thread="100.0", text="ok")
    assert slack_channel.Slack("xoxb", "C1")._route(threaded, ask).ticket == TICKET
    named = channels.Incoming(ref="100.4", text=f"ok pour {TICKET}")
    assert slack_channel.Slack("xoxb", "C1")._route(named, ask).ticket == TICKET


@case
def an_acknowledgement_hangs_where_each_service_counts_threads_from():
    """Slack threads from the first message; Telegram quotes the last one."""
    reply = channels.Reply(channel="", text="oui", ref="100.4", thread="100.0")
    assert slack_channel.Slack("xoxb", "C1")._thread_of(reply) == "100.0"
    assert telegram_channel.Telegram("token", "42")._thread_of(reply) == "100.4"


@case
def slack_reads_the_thread_the_question_opened():
    """A message in a thread never appears in the channel's history."""
    channel = slack_channel.Slack("xoxb-token", "C1")
    answers = {
        "conversations.history": {"ok": True, "messages": [
            {"ts": "100.2", "user": "U1", "text": "et le footer ?"},
            {"ts": "100.1", "bot_id": "B1", "text": "🙋 Blocked · le header"},
            {"ts": "099.9", "user": "U1", "text": "déjà lu"},
        ]},
        "conversations.replies": {"ok": True, "messages": [
            {"ts": "100.0", "bot_id": "B1", "text": "🙋 Blocked · le header"},
            {"ts": "100.3", "user": "U1", "thread_ts": "100.0", "text": "oui"},
        ]},
    }
    with _api(slack_channel, answers):
        incoming, cursor = channel._fetch("100.0", [channels.Ask(ref="100.0", ticket=TICKET)])
    said = [(message.text, message.thread) for message in incoming]
    assert said == [("et le footer ?", ""), ("oui", "100.0")], said
    assert cursor == "100.3", "the newest timestamp seen, whichever call saw it"


@case
def slack_never_reads_its_own_voice_back():
    channel = slack_channel.Slack("xoxb-token", "C1")
    assert channel._read({"ts": "2", "bot_id": "B1", "text": "posted by us"}, "1") is None
    assert channel._read({"ts": "2", "subtype": "channel_join", "user": "U1"}, "1") is None
    assert channel._read({"ts": "1", "user": "U1", "text": "old"}, "1") is None
    assert channel._read({"ts": "2", "user": "U1", "text": "oui"}, "1").text == "oui"


@case
def a_question_outlives_the_run_that_asked_it():
    """An answer typed tomorrow morning still knows which ticket it settles."""
    channel = telegram_channel.Telegram("token", "42")
    with _state():
        with _api(telegram_channel, {"sendMessage": {"ok": True, "result": {"message_id": 1}}}):
            for index in range(channels.ASKS + 3):
                channel.send("?", ticket=f"{index:032d}", title=f"ticket {index}", ask=True)
        remembered = channels._memory()["telegram"]["asks"]
    assert len(remembered) == channels.ASKS, "a bounded memory, not a growing file"
    assert remembered[-1]["title"] == f"ticket {channels.ASKS + 2}"


@case
def a_channel_exists_only_once_both_of_its_values_are_there():
    half = _config('[notify.telegram]\ntoken = "123:abc"\n')
    assert not half.notify.remote and channels.open(half.notify) == []

    whole = _config('[notify.telegram]\ntoken = "123:abc"\nchat = 4242\n')
    assert whole.notify.remote
    assert whole.notify.telegram["chat"] == "4242", "a chat id is compared to JSON, so it is text"
    assert [channel.name for channel in channels.open(whole.notify)] == ["telegram"]

    both = _config(
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
        '[notify.slack]\ntoken = "xoxb"\nchannel = "C1"\n'
    )
    assert [channel.name for channel in channels.open(both.notify)] == ["telegram", "slack"]


@case
def the_switch_that_came_first_still_means_what_it_said():
    """`runner.notify` was the desktop notification, and stays it."""
    assert _config("").notify.desktop is True
    assert _config('[runner]\nnotify = false\n').notify.desktop is False
    assert _config('[runner]\nnotify = false\n\n[notify]\ndesktop = true\n').notify.desktop is True


@case
def a_moment_nobody_named_is_dropped_rather_than_never_sent():
    every = _config("")
    assert every.notify.wants("blocked") and every.notify.wants("done")
    only = _config('[notify]\nevents = ["blocked", "Failed", "merged"]\n')
    assert only.notify.events == ("blocked", "failed"), only.notify.events
    assert not only.notify.wants("done")
    assert not only.notify.wants("merged"), "a typo is not a moment"


@case
def a_value_can_be_written_into_a_table_that_has_a_dot_in_its_name():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n')
    assert C.write_value(path, "notify.telegram", "chat", "4242") is True
    assert C.write_value(path, "notify.telegram", "chat", "4242") is False, "already says that"
    assert C.load(path).notify.telegram["chat"] == "4242"
    assert 'token = "ntn_real"' in path.read_text(), "the rest of the file is untouched"


class _AnsweringClient:
    """A Notion that only has to remember what was written on which page."""

    def __init__(self, error: str = "", asked: list[str] | None = None):
        self.written: list[tuple[str, str]] = []
        self._error = error
        self._asked = asked or []

    def comments(self, page_id: str) -> list[notion.Comment]:
        return [notion.Comment(text, "") for text in self._asked]

    def comment(self, page_id: str, text: str) -> None:
        if self._error:
            raise notion.NotionError(self._error)
        self.written.append((page_id, text))


class _StubChannel(channels.Channel):
    name = "telegram"

    def __init__(self, replies: list[channels.Reply]):
        self._replies = replies
        self.said: list[str] = []

    def collect(self) -> list[channels.Reply]:
        return list(self._replies)

    def acknowledge(self, reply: channels.Reply, text: str) -> bool:
        self.said.append(text)
        return True


@contextmanager
def _channel(stub):
    original = channels.open
    channels.open = lambda settings: [stub]
    try:
        yield stub
    finally:
        channels.open = original


def _answering(
    replies: list[channels.Reply], error: str = "", asked: list[str] | None = None
) -> tuple[Runner, _StubChannel]:
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config('[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n')
    runner.client = _AnsweringClient(error, asked)
    runner._comments = {}
    runner.dry_run = False
    runner.quiet = True
    stub = _StubChannel(replies)
    with _channel(stub):
        runner.answers()
    return runner, stub


@case
def an_answer_from_a_phone_becomes_the_comment_that_wakes_the_ticket():
    """One path, not two: the reply is a comment, and comments already wake."""
    runner, stub = _answering(
        [channels.Reply(channel="telegram", text="oui", ticket=TICKET, title="Le header")]
    )
    assert len(runner.client.written) == 1
    page, text = runner.client.written[0]
    assert page == TICKET
    assert "go ahead" in text
    assert not text.startswith("ponos@"), (
        "signed as ours, the answer would close the ticket instead of waking it"
    )
    assert stub.said and "Le header" in stub.said[0], "an answer nobody confirms is a phone call"


@case
def a_message_that_answers_nothing_is_never_written_to_a_ticket():
    runner, stub = _answering([channels.Reply(channel="telegram", text="tiens, une idée")])
    assert runner.client.written == []
    assert stub.said == [], "a bot that answers ordinary talk is a bot nobody keeps"

    runner, stub = _answering([channels.Reply(channel="telegram", text="oui")])
    assert runner.client.written == []
    assert stub.said, "a yes that landed nowhere was meant for us, and is told it missed"


@case
def a_notion_that_refuses_the_answer_says_so_where_it_was_typed():
    runner, stub = _answering(
        [channels.Reply(channel="telegram", text="oui", ticket=TICKET, title="Le header")],
        error="403 API token does not have access",
    )
    assert runner.client.written == []
    assert "403" in stub.said[0]


@case
def a_blocked_ticket_travels_with_its_question_and_its_link():
    sent: list[dict] = []
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    )
    runner.dry_run = False
    runner.quiet = True
    ticket = type("T", (), {
        "page": notion.Page(id=TICKET, url="https://notion.so/t", title="Le header"),
        "id": TICKET,
        "title": "Le header",
        "url": "https://notion.so/t",
    })()

    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append({"text": text, **rest})
    try:
        with _state_home():
            runner._tell(
                "blocked", ticket, "blocked",
                "Which header — the dashboard one or the public site?",
                ask=True,
            )
    finally:
        channels.announce = original

    assert len(sent) == 1
    message = sent[0]
    assert message["text"].startswith("🙋 Stuck · Le header"), "the comment's own verdict"
    assert "Which header" in message["text"], "the agent's question, not the runner's summary"
    assert "https://notion.so/t" in message["text"], "a notification you have to go and find"
    assert "An answer here" not in message["text"], "the question says how to answer it"
    assert message["ask"] is True and message["ticket"] == TICKET


@case
def nothing_is_sent_anywhere_during_a_dry_run():
    sent: list[str] = []
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config('[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n')
    runner.dry_run = True
    runner.quiet = True
    ticket = type("T", (), {
        "page": notion.Page(id=TICKET, url="u", title="t"), "title": "t", "url": "u",
    })()
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
    try:
        runner._tell("done", ticket, "review", "branch")
    finally:
        channels.announce = original
    assert sent == []


@contextmanager
def _notifying(*, missing: str = ""):
    """The tools a notification uses, replaced by a note of what they were asked.

    One of them can be taken away, because on a real machine one of them is: a
    box with no `gdbus`, a session with no `xdg-open`. None of that is allowed
    to cost the notification itself.
    """
    launched: list[list[str]] = []
    tools = ("notify-send", "gdbus", "dbus-monitor", "xdg-open")
    found = {name: f"/usr/bin/{name}" for name in tools if name != missing}

    def run(command, **rest):
        launched.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    originals = (shutil.which, subprocess.run, subprocess.Popen)
    shutil.which = lambda name: found.get(name)
    subprocess.run = run
    subprocess.Popen = lambda command, **rest: launched.append(command)
    try:
        yield launched
    finally:
        shutil.which, subprocess.run, subprocess.Popen = originals


@case
def a_desktop_notification_takes_you_to_the_ticket_it_names():
    """A line on screen you cannot follow is a title you then go and hunt for."""
    with _notifying() as launched:
        assert notify.send(
            "Blocked · Le header", "Which header?", link="https://notion.so/t"
        )
    assert len(launched) == 1, "the plain notification is not sent on top of the clickable one"
    command = launched[0]
    assert command[1:3] == ["-m", "ponos.notify"], (
        "the click is waited for beside the run, never inside it"
    )
    assert command[3:] == [
        "https://notion.so/t", "Blocked · Le header", "Which header?", "normal",
        "Open the ticket", "plain",
    ]

    with _notifying() as launched:
        notify.send(
            "To review · t", "PR #42", link="https://notion.so/t", warning=True,
            buttons=(("See the PR", "https://github.com/o/r/pull/42"),
                     ("Open the ticket", "https://notion.so/t")),
        )
    assert launched[0][8:] == [
        "warning", "See the PR", "https://github.com/o/r/pull/42",
        "Open the ticket", "https://notion.so/t",
    ], "each button travels to the child with where it goes"


@case
def a_notification_with_nowhere_to_go_is_a_notification_all_the_same():
    for tool in ("gdbus", "dbus-monitor", "xdg-open"):
        with _notifying(missing=tool) as launched:
            assert notify.send("Ready to review · t", "branch", link="https://notion.so/t")
        assert launched[0][0] == "/usr/bin/notify-send", f"sent anyway, without {tool}"

    with _notifying() as launched:
        assert notify.send("Ponos updated", "0.4.0")
    assert launched[0][0] == "/usr/bin/notify-send", "nothing to open, so nothing to follow"

    with _notifying(missing="notify-send") as launched:
        assert notify.send("Ponos updated", "0.4.0") is False
    assert launched == []


@case
def the_notification_posted_over_dbus_is_the_one_notify_send_would_have_sent():
    posted: list[list[str]] = []
    original = subprocess.run
    subprocess.run = lambda command, **rest: (
        posted.append(command) or subprocess.CompletedProcess(command, 0, "(uint32 42,)\n", "")
    )
    try:
        assert notify._post("Blocked · t", '42 "why"', urgent=True, warning=True) == "42"
        assert notify._post(
            "To review · t", "PR #42", urgent=False,
            buttons=(("See the PR", "https://github.com/o/r/pull/42"),),
        ) == "42"
    finally:
        subprocess.run = original
    command = posted[0]
    assert "--" in command, "`-1` is an expiry, and gdbus would read it as an option"
    assert command[command.index("--") + 1:] == [
        '"Ponos"', "0", '"dialog-warning"', '"Blocked · t"', '"42 \\"why\\""',
        '["default", "Open the ticket"]', "{'urgency': <byte 2>}", "-1",
    ], "a body is a string, even when it reads like a number"
    command = posted[1]
    tail = command[command.index("--") + 1:]
    assert tail[2] == f'"{notify.ICON}"', "Ponos's own icon, not the information sign"
    assert tail[5] == '["default", "Open the ticket", "open-0", "See the PR"]'
    assert tail[6] == "{'urgency': <byte 1>}"


@case
def the_icon_of_ponos_falls_back_on_the_system_ones():
    assert notify.ICON.is_file(), "the mascot's icon ships with the runner"
    assert notify._icon(False) == str(notify.ICON)
    assert notify._icon(True) == "dialog-warning", "a failure says so by its icon"
    original = notify.ICON
    notify.ICON = original.with_name("missing.png")
    try:
        assert notify._icon(False) == "dialog-information"
    finally:
        notify.ICON = original


@case
def only_a_click_opens_the_page_and_a_dismissal_never_does():
    """`dbus-monitor` says it over several lines, and about every notification."""
    def watching(*lines):
        return type("W", (), {"stdout": iter(lines)})()

    clicked = watching(
        "signal ... interface=org.freedesktop.Notifications; member=ActionInvoked\n",
        "   uint32 7\n",
        '   string "default"\n',
    )
    assert notify._clicked(clicked, "7") == "default"

    button = watching(
        "signal ... interface=org.freedesktop.Notifications; member=ActivationToken\n",
        "   uint32 7\n",
        '   string "token"\n',
        "signal ... interface=org.freedesktop.Notifications; member=ActionInvoked\n",
        "   uint32 7\n",
        '   string "open-0"\n',
    )
    assert notify._clicked(button, "7") == "open-0", "which button, not only that one was"

    dismissed = watching(
        "signal ... interface=org.freedesktop.Notifications; member=NotificationClosed\n",
        "   uint32 7\n",
        "   uint32 2\n",
    )
    assert not notify._clicked(dismissed, "7")

    somebody_else = watching(
        "signal ... interface=org.freedesktop.Notifications; member=ActionInvoked\n",
        "   uint32 9\n",
        '   string "default"\n',
    )
    assert not notify._clicked(somebody_else, "7"), "another application's notification"


@case
def a_ticket_notification_carries_its_page_to_the_screen_too():
    seen: list[dict] = []
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config("")
    runner.dry_run = False
    runner.quiet = True
    ticket = type("T", (), {
        "page": notion.Page(id=TICKET, url="https://notion.so/t", title="t"),
        "id": TICKET,
        "title": "t",
        "url": "https://notion.so/t",
    })()
    original = notify.send
    notify.send = lambda title, body, **rest: seen.append({"title": title, **rest})
    try:
        with _state_home():
            runner._tell("done", ticket, "review", "branch")
    finally:
        notify.send = original
    assert seen == [{"title": "To review", "urgent": False, "warning": False,
                     "link": "https://notion.so/t", "action": "Open the ticket",
                     "buttons": ()}]

    seen.clear()
    runner.config.runner.language = "fr"
    notify.send = lambda title, body, **rest: seen.append({"title": title, **rest})
    try:
        with _state_home():
            runner._tell("done", ticket, "review", "branch")
    finally:
        notify.send = original
    assert seen[0]["title"] == "À relire" and seen[0]["action"] == "Ouvrir le ticket"

    seen.clear()
    pull = "https://github.com/o/r/pull/42"
    notify.send = lambda title, body, **rest: seen.append({"title": title, "body": body, **rest})
    try:
        with _state_home():
            runner._tell(
                "done", ticket, "review", f"PR #42 · 3 commits · 4 minutes · 0,82 $\nDone.\n{pull}",
                project="Leadz", facts=("PR #42", "3 commits"), summary="Done.",
                pull_request=pull,
            )
            runner._tell("blocked", ticket, "blocked", "Which one?", ask=True, summary="Which one?")
            runner._tell("failed", ticket, "failed", "It broke.")
    finally:
        notify.send = original
    review, blocked, failed = seen
    assert review["title"] == "À relire — Leadz"
    assert review["body"] == "t\nDone.", "no address, price, or duration"
    assert review["buttons"] == (("Voir la PR", pull), ("Ouvrir le ticket", "https://notion.so/t"))
    assert blocked["title"] == "Ponos a une question" and blocked["urgent"] is True
    assert blocked["body"] == "t\nWhich one?\nRéponds dans le ticket"
    assert failed["urgent"] is False and failed["warning"] is True, "a failure goes away by itself"
    assert failed["buttons"] == ()


@case
def a_desktop_notification_says_what_happened_where_and_what_to_do():
    """The comment's words do not fit a desktop: see `Voice.desktop`."""
    said = voice.Voice("fr")
    title, body = said.desktop(
        "review",
        "Leadz — [Audit] Tester l'app en prod via Claude in Chrome (créer, modifier, supprimer)",
        project="Leadz",
        summary="Le formulaire est refait : puces pour la catégorie et le type, bouton désactivé "
        "sans titre, message d'erreur sous chaque champ et focus sur le premier champ fautif.",
    )
    assert title == "À relire — Leadz", "the event and the project, the whole of a lock screen"
    ticket, sentence = body.split("\n")
    assert ticket == "[Audit] Tester l'app en prod via Claude in Chrome (créer…", ticket
    assert len(ticket) <= voice.TITLE + 1, "the title is cut on a word, with an ellipsis"
    assert sentence.endswith("…") and len(sentence) <= voice.GIST + 1, sentence
    assert sentence.startswith("Le formulaire est refait : puces"), "French spacing is kept"
    assert not sentence[:-1].endswith(" "), "cut on a word"

    # Markdown, addresses and markup, none of which a desktop can draw or follow.
    title, body = said.desktop(
        "review", "Leadz — Fix `the` form", project="Leadz",
        summary="Done in **two** steps, see [the doc](https://x.y/doc) and "
        "https://github.com/o/r/pull/9 — <b>Tom</b> & `snake_case` kept.",
    )
    assert title == "À relire — Leadz"
    assert body == (
        "Fix the form\n"
        "Done in two steps, see the doc and — &lt;b&gt;Tom&lt;/b&gt; &amp; snake_case kept."
    ), body
    assert "http" not in body and "`" not in body and "**" not in body

    # A question, said as one, without the options it cannot be answered with.
    title, body = said.desktop("blocked", "Ponos — Which header?", summary="Quel en-tête ?")
    assert title == "Ponos a une question — Ponos"
    assert body == "Which header?\nQuel en-tête ?\nRéponds dans le ticket"
    assert voice.Voice("en").desktop("blocked", "t", summary="x") == (
        "Ponos has a question", "t\nx\nAnswer in the ticket"
    )

    # Never a bare "Ponos" with nothing under it, and a sentence even when the
    # session said none.
    assert said.desktop("failed", "Adam — Corriger le formulaire") == (
        "Ticket en erreur — Adam", "Corriger le formulaire\nLe travail s'est arrêté sur une erreur"
    )
    assert said.desktop("review", "Adam — Corriger le formulaire", project="Adam") == (
        "À relire — Adam", "Corriger le formulaire\nUne pull request est prête"
    )
    assert said.desktop("merged", "Adam — Une tâche", project="Adam")[0] == "Ticket terminé — Adam"
    assert said.desktop("prepared", "Portfolio — Une tâche")[0] == "À valider — Portfolio"
    assert said.desktop("read", "Résumé", project="Leadz")[0] == "À lire — Leadz"
    # No project to compare to: only a short prefix is taken for one.
    assert said.desktop("failed", "Corriger le bug du formulaire - côté serveur")[0] == (
        "Ticket en erreur"
    )
    assert said.desktop("failed", "Corriger le bug du formulaire - côté serveur")[1].startswith(
        "Corriger le bug du formulaire - côté serveur\n"
    ), "the ticket's name is whole when it fits"


@case
def a_ticket_that_speaks_again_replaces_its_notification_instead_of_stacking():
    posted: list[list[str]] = []
    original = subprocess.run
    subprocess.run = lambda command, **rest: (
        posted.append(command) or subprocess.CompletedProcess(command, 0, "(uint32 7,)\n", "")
    )
    try:
        assert notify._post("t", "b", urgent=False, replaces="5", key="https://notion.so/t") == "7"
    finally:
        subprocess.run = original
    tail = posted[0][posted[0].index("--") + 1:]
    assert tail[1] == "5", "posted over the ticket's last one"
    assert tail[6] == (
        "{'urgency': <byte 1>, 'x-canonical-private-synchronous': <\"https://notion.so/t\">}"
    )

    with _state_home():
        assert notify._remembered("https://notion.so/t") == {}
        notify._remember("https://notion.so/t", "7", {})
        assert notify._remembered("https://notion.so/t")["id"] == "7"
        assert notify._remembered("https://notion.so/other") == {}

    with _notifying() as launched:
        notify.send("t", "b")
    assert "string:x-canonical-private-synchronous:" not in " ".join(launched[0])
    with _notifying(missing="gdbus") as launched:
        notify.send("t", "b", link="https://notion.so/t")
    assert launched[0][launched[0].index("--hint") + 1] == (
        "string:x-canonical-private-synchronous:https://notion.so/t"
    )


@case
def the_icon_of_ponos_is_cut_out_in_the_sizes_a_desktop_asks_for():
    """An opaque square is drawn by a desktop as a black one."""
    import struct
    import zlib

    for size in (48, 64, 128, 256):
        data = (notify.ICON.parent / f"ponos-{size}.png").read_bytes()
        width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
        assert (width, height) == (size, size) and colour == 6, "RGBA, so with an alpha channel"
    assert notify.ICON.name == "ponos-256.png"


def _png_pixels(data: bytes) -> list[tuple[int, int, int, int]]:
    """The pixels of an 8-bit RGBA PNG, unfiltered — enough to read a colour."""
    import struct
    import zlib

    width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
    assert depth == 8 and colour == 6, "an 8-bit RGBA PNG"
    chunks, at = b"", 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at : at + 8])
        if kind == b"IDAT":
            chunks += data[at + 8 : at + 8 + length]
        at += 12 + length
    raw, stride, rows, previous = zlib.decompress(chunks), width * 4, [], bytearray(width * 4)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for x in range(stride):
            left = line[x - 4] if x >= 4 else 0
            up, corner = previous[x], previous[x - 4] if x >= 4 else 0
            if kind == 1:
                line[x] = (line[x] + left) & 255
            elif kind == 2:
                line[x] = (line[x] + up) & 255
            elif kind == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                near = min((abs(guess - left), left), (abs(guess - up), up), (abs(guess - corner), corner), key=lambda pair: pair[0])
                line[x] = (line[x] + near[1]) & 255
        rows.append(line)
        previous = line
    return [tuple(row[x : x + 4]) for row in rows for x in range(0, stride, 4)]


@case
def the_icon_of_a_notification_is_the_orange_mascot_and_the_mascot_script_draws_it():
    """The desktop icons were cut by hand once, and stayed blue when the robot went orange.

    They are the mascot's like the app icons are, so `scripts/mascot.mjs` writes
    them with the rest — and a vivid pixel of the robot is Hermez orange, red
    well above blue, never the blue it used to be.
    """
    for size in (48, 256):
        pixels = _png_pixels((notify.ICON.parent / f"ponos-{size}.png").read_bytes())
        vivid = [(r, g, b) for r, g, b, a in pixels if a > 200 and max(r, g, b) - min(r, g, b) > 80]
        assert vivid, f"ponos-{size}.png has no colour at all"
        orange = sum(1 for r, g, b in vivid if r > b + 60)
        assert orange > len(vivid) * 0.6, f"ponos-{size}.png is not the orange mascot ({orange}/{len(vivid)})"
    script = (ROOT / "scripts/mascot.mjs").read_text(encoding="utf-8")
    assert "'src', 'ponos', 'icons'" in script, "the desktop icons are not written from the mascot"


# -- the bell ----------------------------------------------------------------


@case
def only_the_moments_that_need_you_ring_the_bell():
    from ponos import notifications
    assert notifications.kind_of("review") == "review"
    assert notifications.kind_of("failed") == "failed"
    assert notifications.kind_of("blocked", "session.question") == "question"
    assert notifications.kind_of("blocked", "worktree.interrupted") == "question"
    assert notifications.kind_of("blocked", "merge.checks-failed") == "ci"
    assert notifications.kind_of("blocked", "merge.refused") == "blocked"
    assert notifications.kind_of("blocked") == "question", "a stop with no cause is a question asked"
    for routine in ("published", "merged", "read", "prepared", "waiting", "requeued"):
        assert notifications.kind_of(routine) == "", routine


@case
def the_bell_keeps_what_is_unread_once_and_forgets_what_was_read_after_thirty_days():
    from ponos import notifications
    with _state_home():
        notifications.add("question", "a", "Le header")
        notifications.add("question", "a", "Le header")  # asked twice before anyone looked
        notifications.add("review", "a", "Le header")
        notifications.add("routine", "a", "never")
        heard = notifications.recent()
        assert heard["unread"] == 2
        assert [item["kind"] for item in heard["items"]] == ["review", "question"], "newest first"
        assert all(item["read"] is False and item["ticket"] == "a" for item in heard["items"])

        notifications.read(heard["items"][0]["id"])
        assert notifications.recent()["unread"] == 1
        notifications.add("review", "a", "Le header")  # read: a new one may ring
        assert notifications.recent()["unread"] == 2

        notifications.read()
        heard = notifications.recent()
        assert heard["unread"] == 0 and len(heard["items"]) == 3 and all(i["read"] for i in heard["items"])

        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
        with db.transaction() as connection:
            connection.execute("UPDATE notifications SET read_at = ? WHERE id = ?", (old, heard["items"][2]["id"]))
        notifications.read()
        assert len(notifications.recent()["items"]) == 2, "read more than thirty days ago: purged"


@case
def a_question_a_review_and_a_failure_ring_the_bell_but_a_dry_run_does_not():
    from ponos import notifications
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config("")
    # The bell is what is under test: a real notification here would land on the
    # screen of whoever runs the suite, titled "Question · t".
    runner.config.notify.desktop = False
    runner.quiet = True
    ticket = type("T", (), {
        "page": notion.Page(id=TICKET, url="u", title="t"), "id": TICKET, "title": "t", "url": "u",
    })()
    with _state_home():
        runner.dry_run = True
        runner._tell("done", ticket, "review", "branch")
        assert notifications.recent()["unread"] == 0
        runner.dry_run = False
        runner._tell("done", ticket, "published", "merged")
        assert notifications.recent()["unread"] == 0, "routine"
        runner._tell("blocked", ticket, "blocked", "Which?", ask=True, code="session.question")
        runner._tell("done", ticket, "review", "branch")
        assert [i["kind"] for i in notifications.recent()["items"]] == ["review", "question"]


# -- clean, and the branch a failure leaves behind ----------------------------


@contextmanager
def _git_answering(**answers):
    """git and gh, replaced by what they would have said."""
    from ponos import git as git_module

    original = {name: getattr(git_module, name) for name in answers}
    for name, replacement in answers.items():
        setattr(git_module, name, replacement)
    try:
        yield
    finally:
        for name, replacement in original.items():
            setattr(git_module, name, replacement)


def _cleaning(worktrees: dict[str, dict]) -> tuple[str, list[str]]:
    """Run `clean --force` over invented worktrees, and see which branches went.

    Each entry is a directory under `worktrees/`, and what git and gh would say
    of it: the branch it is on, whether that branch is pushed, the pull request
    `gh` finds on it, how many commits it has of its own, and whether anything
    in it was never committed.
    """
    from ponos import git as git_module

    deleted: list[str] = []
    with _state_home() as state_root, tempfile.TemporaryDirectory() as repository:
        repo = Path(repository)
        (repo / ".git").mkdir()
        root = state_root / "worktrees"
        root.mkdir(parents=True)
        for name in worktrees:
            (root / name).mkdir()
            # What a linked worktree carries, and what `clean` now asks for
            # before it lets any repository answer for a directory.
            (root / name / ".git").write_text(f"gitdir: {repo}/.git/worktrees/{name}\n")

        def facts(worktree) -> dict:
            return worktrees[Path(worktree).name]

        def raw(args, cwd, timeout=300, **kept):
            if args[1:2] == ["--path-format=absolute"]:
                return git_module.Result(0, str(repo / ".git"), "")
            if args == ["worktree", "list", "--porcelain"]:
                listed = "\n".join(f"worktree {root / name}" for name in worktrees)
                return git_module.Result(0, f"worktree {repo}\n{listed}", "")
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return git_module.Result(0, facts(cwd)["branch"], "")
            raise AssertionError(f"clean asked git something unexpected: {args}")

        def delete(_repo, branch):
            deleted.append(branch)
            return git_module.Result(0, f"Deleted branch {branch}", "")

        pushed = {f"origin/{f['branch']}" for f in worktrees.values() if f.get("pushed")}
        requests = {f["branch"]: f.get("pull_request", "") for f in worktrees.values()}
        printed = io.StringIO()
        previous = os.environ.get("PONOS_CONFIG")
        os.environ["PONOS_CONFIG"] = str(repo / "nothing.toml")
        try:
            with _git_answering(
                git=raw,
                default_branch=lambda _repo: "main",
                has_ref=lambda _repo, reference: reference in {"main", "origin/main"} | pushed,
                pull_request_on=lambda _repo, branch, accounts=None: requests.get(branch, ""),
                commits_ahead=lambda worktree, _base: facts(worktree).get("commits", 0),
                is_dirty=lambda worktree: facts(worktree).get("dirty", False),
                remove_worktree=lambda _repo, worktree: shutil.rmtree(worktree),
                delete_branch=delete,
            ), contextlib.redirect_stdout(printed):
                assert cli_main(["clean", "--force"]) == 0
        finally:
            if previous is None:
                os.environ.pop("PONOS_CONFIG", None)
            else:
                os.environ["PONOS_CONFIG"] = previous
    return _plain(printed.getvalue()), deleted


@case
def clean_leaves_the_worktrees_of_a_run_in_progress_alone():
    """`clean --force` beside a running pass would remove the worktree a
    session is writing in: kept by a failure or in use, nothing on disk tells
    the two apart. It takes the run lock, or it does nothing."""
    with _state_home() as state_root:
        kept = state_root / "worktrees" / "app-1a2b3c4d"
        kept.mkdir(parents=True)
        printed = io.StringIO()
        with state.lock(), contextlib.redirect_stdout(printed):
            assert cli_main(["clean", "--force"]) == 1
        assert kept.exists(), "a worktree was removed under a running pass"
        assert "run is in progress" in _plain(printed.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli_main(["clean", "--force"]) == 0
        assert not kept.exists(), "and once the pass is over, it goes"


@case
def a_scratch_directory_never_speaks_for_the_repository_around_it():
    """`git rev-parse` in a directory that is no repository climbs to its
    parents — and the state directory may well sit inside one. `clean` would
    then prune that repository's worktrees and delete its branches."""
    from ponos import git as git_module

    with tempfile.TemporaryDirectory() as directory:
        outer = Path(directory) / "home"
        outer.mkdir()
        quiet = {"capture_output": True, "check": True}
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(outer)], **quiet)
        identity = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", *identity, "-C", str(outer), "commit", "--quiet", "--allow-empty", "-m", "one"], **quiet)
        scratch = outer / ".local" / "state" / "ponos" / "scratch" / "deliver-1a2b3c4d"
        scratch.mkdir(parents=True)
        assert git_module.repository_of(scratch) is None, "a scratch directory is no worktree"

        cloned = scratch.parent / "cloned-1a2b3c4d"
        subprocess.run(["git", "init", "--quiet", str(cloned)], **quiet)
        assert git_module.repository_of(cloned) is None, "a clone made in one is not either"

        worktree = scratch.parent.parent / "worktrees" / "home-1a2b3c4d"
        subprocess.run(
            ["git", "-C", str(outer), "worktree", "add", "--quiet", "-b", "ticket/x", str(worktree)],
            **quiet,
        )
        found = git_module.repository_of(worktree)
        assert found is not None and found.resolve() == outer.resolve(), found

        # A `.git` file that names a repository which does not list it back.
        (scratch / ".git").write_text(f"gitdir: {outer}/.git/worktrees/home-1a2b3c4d\n")
        assert git_module.repository_of(scratch) is None


@case
def clean_removes_the_branch_that_would_block_the_ticket_for_ever():
    """A branch name comes from the ticket's ID, so it is the same one every time.

    A session that failed without committing leaves the worktree and the branch;
    `add_worktree` then refuses that ticket for good. Removing the directory and
    leaving the branch — which is what `clean` used to do — changed nothing.
    """
    printed, deleted = _cleaning(
        {"trader-ia-16e26e94": {"branch": "ticket/ameliorer-la-doc-16e26e94"}}
    )
    assert deleted == ["ticket/ameliorer-la-doc-16e26e94"]
    assert "removed branch ticket/ameliorer-la-doc-16e26e94" in printed


@case
def clean_never_removes_a_branch_that_carries_something_of_its_own():
    """The refusal `clean` lifts is also what protects the previous session's work.

    A commit that was never pushed — the push failed, and the branch is all
    that is left of it — an open pull request, or a worktree with uncommitted
    changes: each of those stays, and the output says which and why, because
    that ticket is going to stay blocked until somebody looks at it.
    """
    printed, deleted = _cleaning(
        {
            "unpushed": {"branch": "ticket/ameliorer-la-doc-16e26e94", "commits": 1},
            "reviewed": {
                "branch": "ticket/le-header-9d2cb790",
                "pushed": True,
                "pull_request": "https://github.com/x/y/pull/12",
                "commits": 2,
            },
            "unsaved": {"branch": "ticket/le-bandeau-3ca45168", "dirty": True},
        }
    )
    assert deleted == []
    assert "ticket/ameliorer-la-doc-16e26e94 kept — 1 commit(s)" in printed
    assert "ticket/le-header-9d2cb790 kept — it is pushed" in printed
    assert "https://github.com/x/y/pull/12" in printed
    assert "ticket/le-bandeau-3ca45168 kept — the worktree has changes" in printed
    assert printed.count("branch -D ") == 3, "each kept branch says what is left to do"


# -- worktrees ---------------------------------------------------------------


def _worktree_for(
    branch="ticket/le-header-9d2cb790",
    *,
    refs=("main", "origin/main"),
    held="",
    held_here=False,
    commits=0,
    dirty=False,
    rebase="",
    path_exists=False,
):
    """Make the ticket's worktree against an invented repository.

    `refs` is what git can resolve, `held` the worktree that already has the
    branch checked out — `held_here` when that worktree is the ticket's own —
    and `rebase` what a rebase would print instead of working.
    Returns what `add_worktree` answered — or the GitError it raised — and every
    command it ran, which is where the interesting part of this lives.
    """
    from ponos import git as git_module

    commands: list[list[str]] = []

    def fake(args, cwd, timeout=300, **_):
        commands.append(list(args))
        head = args[:1]
        if args[:3] == ["rev-parse", "--verify", "--quiet"]:
            return git_module.Result(0 if args[3] in refs else 1, "", "")
        if args[:2] == ["worktree", "list"]:
            listing = f"worktree {held}\nHEAD abc\nbranch refs/heads/{branch}\n" if held else ""
            return git_module.Result(0, listing, "")
        if head == ["rev-list"]:
            return git_module.Result(0, str(commits), "")
        if args[:2] == ["status", "--porcelain"]:
            return git_module.Result(0, "M src/x.py" if dirty else "", "")
        if args[:2] == ["rebase", "--autostash"]:
            if rebase:
                return git_module.Result(1, f"CONFLICT (content): {rebase}", "error: could not apply")
            return git_module.Result(0, "", "")
        return git_module.Result(0, "", "")

    with tempfile.TemporaryDirectory() as home:
        repo, path = Path(home) / "repo", Path(home) / "worktrees" / "site-9d2cb790"
        if held_here:
            held = str(path)
        if path_exists:
            path.mkdir(parents=True)
            # What a worktree has instead of a repository: the file that points
            # back at the one it belongs to.
            (path / ".git").write_text(f"gitdir: {repo}/.git/worktrees/site-9d2cb790\n")
        with _git_answering(git=fake):
            try:
                made = git_module.add_worktree(repo, path, branch, "main")
            except git_module.GitError as error:
                made = error
    return made, commands


def _one(commands: list[list[str]], prefix: list[str]) -> list[str]:
    """The one command that starts like that — there is never a second."""
    found = [command for command in commands if command[: len(prefix)] == prefix]
    assert len(found) == 1, f"{prefix} ran {len(found)} time(s): {commands}"
    return found[0]


def _aged_page(page_id: str, status: str, edited_days_ago: float) -> notion.Page:
    edited = datetime.now(timezone.utc) - timedelta(days=edited_days_ago)
    return notion.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"Status": {"type": "status", "status": {"name": status}}},
        raw={"last_edited_time": edited.isoformat()},
    )


class _BoardOf:
    """A board that answers one query — every ticket — and nothing else."""

    def __init__(self, pages: list[notion.Page], error: str = "") -> None:
        self._pages = pages
        self._error = error

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        if self._error:
            raise notion.NotionError(self._error)
        return self._pages


def _tidying(pages: list[notion.Page], body: str = "", error: str = "") -> Runner:
    runner = _bare_runner(_BoardOf(pages, error))
    runner.config = _config(body)
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    return runner


def _aged(path: Path, days: float, *, directory: bool = True) -> Path:
    if directory:
        path.mkdir(parents=True)
        (path / "work.txt").write_text("x" * 1000)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("log")
    moment = time.time() - days * 86400
    os.utime(path, (moment, moment))
    return path


@case
def a_pass_tidies_what_done_tickets_left_and_nothing_else():
    """The ticket: 44 worktrees, 25 GB, because `clean` only ran when somebody
    typed it. A pass now applies the retention once a day — and the board says
    what may go: done for long enough, or a scratch directory nobody can reach."""
    tail = {name: f"{index:08x}" for index, name in enumerate(
        ["done", "fresh", "blocked", "review", "claimed", "gone", "gone2"], start=0x1a2b3c40
    )}
    pages = [
        _aged_page(f"page-{tail['done']}", "Done", 30),
        _aged_page(f"page-{tail['fresh']}", "Done", 2),
        _aged_page(f"page-{tail['blocked']}", "Blocked", 30),
        _aged_page(f"page-{tail['review']}", "In review", 30),
        _aged_page(f"page-{tail['claimed']}", "Done", 30),
    ]
    with _state_home() as root:
        worktrees, scratch = root / "worktrees", root / "scratch"
        done = _aged(worktrees / f"app-{tail['done']}", 30)
        done_scratch = _aged(scratch / f"deliver-{tail['done']}", 30)
        fresh = _aged(worktrees / f"app-{tail['fresh']}", 30)
        blocked = _aged(worktrees / f"app-{tail['blocked']}", 30)
        blocked_scratch = _aged(scratch / f"notes-{tail['blocked']}", 30)
        review = _aged(worktrees / f"app-{tail['review']}", 30)
        claimed = _aged(worktrees / f"app-{tail['claimed']}", 30)
        orphan = _aged(scratch / f"notes-{tail['gone']}", 30)
        orphan_worktree = _aged(worktrees / f"app-{tail['gone2']}", 30)
        young_orphan = _aged(scratch / f"kind-{tail['gone2']}", 1)
        old_log = _aged(root / "logs" / "old.jsonl", 30, directory=False)
        new_log = _aged(root / "logs" / "new.jsonl", 1, directory=False)
        state.claim(f"page-{tail['claimed']}", "Validated")

        runner = _tidying(pages)
        tidied = runner.tidy()
        assert tidied is not None
        assert not done.exists() and not done_scratch.exists(), "done for a month: gone"
        assert not orphan.exists(), "a scratch directory whose ticket left the board: gone"
        assert not old_log.exists() and new_log.exists()
        for kept in (fresh, blocked, blocked_scratch, review, claimed, orphan_worktree, young_orphan):
            assert kept.exists(), f"{kept.name} was removed"
        assert tidied.logs == 1 and tidied.freed >= 3000, tidied
        assert runner.tidy() is None, "once a day, not every pass"


@case
def a_done_tickets_worktree_with_uncommitted_work_is_kept():
    with _state_home() as root:
        worktree = _aged(root / "worktrees" / "app-1a2b3c4d", 30)
        removed: list[Path] = []
        with _git_answering(
            repository_of=lambda _path: root,
            is_dirty=lambda _path: True,
            remove_worktree=lambda _repo, path: removed.append(path),
        ):
            _tidying([_aged_page("page-1a2b3c4d", "Done", 30)]).tidy()
        assert worktree.exists() and not removed
        with _git_answering(
            repository_of=lambda _path: root,
            is_dirty=lambda _path: False,
            remove_worktree=lambda _repo, path: (removed.append(path), shutil.rmtree(path)),
        ):
            _tidying([_aged_page("page-1a2b3c4d", "Done", 30)]).tidy(now=True)
        assert removed == [worktree] and not worktree.exists()


@case
def a_board_that_cannot_be_read_tidies_the_logs_and_nothing_else():
    """No board, no verdict: an unreadable one — or an empty one, which is more
    likely a board not read than a board whose every ticket was deleted —
    removes no directory at all."""
    with _state_home() as root:
        scratch = _aged(root / "scratch" / "notes-1a2b3c4d", 30)
        log = _aged(root / "logs" / "old.jsonl", 30, directory=False)
        _tidying([], error="502 bad gateway").tidy()
        assert scratch.exists() and not log.exists()
        _tidying([]).tidy(now=True)
        assert scratch.exists(), "an empty board orphaned everything"


@case
def the_retention_can_be_turned_off():
    with _state_home() as root:
        scratch = _aged(root / "scratch" / "notes-1a2b3c4d", 30)
        page = _aged_page("page-1a2b3c4d", "Done", 30)
        _tidying([page], "[runner]\nclean_done_worktrees = false\n").tidy()
        assert scratch.exists()
        _tidying([page], "[runner]\nlog_retention_days = 0\n").tidy(now=True)
        assert scratch.exists()
        example = (ROOT / "config.example.toml").read_text(encoding="utf-8")
        assert "clean_done_worktrees = true" in example


@case
def a_cancelled_ticket_loses_its_worktree_like_a_done_one_and_a_validated_one_keeps_it():
    with _state_home() as root:
        cancelled = _aged(root / "worktrees" / "app-1a2b3c41", 30)
        validated = _aged(root / "worktrees" / "app-1a2b3c42", 20)
        pages = [
            _aged_page("page-1a2b3c41", "Cancelled", 30),
            _aged_page("page-1a2b3c42", "Validated", 30),
        ]
        with _git_answering(
            repository_of=lambda _path: root,
            is_dirty=lambda _path: False,
            unpushed=lambda _path: 0,
            current_branch=lambda _path: "",
            remove_worktree=lambda _repo, path: shutil.rmtree(path),
        ):
            _tidying(pages).tidy()
        assert not cancelled.exists() and validated.exists()


@case
def a_forgotten_worktree_goes_unless_its_ticket_runs_or_it_holds_work_nobody_else_has():
    tail = ["1a2b3c51", "1a2b3c52", "1a2b3c53", "1a2b3c54", "1a2b3c55", "1a2b3c56", "1a2b3c57"]
    pages = [
        _aged_page(f"page-{tail[0]}", "Failed", 40),
        _aged_page(f"page-{tail[1]}", "In progress", 40),
        _aged_page(f"page-{tail[2]}", "Blocked", 40),
        _aged_page(f"page-{tail[3]}", "Blocked", 40),
        _aged_page(f"page-{tail[4]}", "Blocked", 3),
    ]
    with _state_home() as root:
        names = ["failed", "running", "dirty", "unpushed", "young", "gone", "stray"]
        places = {
            name: _aged(root / "worktrees" / f"app-{owner}", 3 if name == "young" else 40)
            for name, owner in zip(names, tail)
        }
        # Not a worktree any repository knows: not ours to guess about.
        (places["stray"] / "notes.txt").write_text("x")
        branches: list[str] = []

        def dirty(path):
            return path.name.endswith(tail[2])

        def unpushed(path):
            return 2 if path.name.endswith(tail[3]) else 0

        def repository_of(path):
            return None if path.name.endswith(tail[6]) else root

        with _git_answering(
            repository_of=repository_of,
            is_dirty=dirty,
            unpushed=unpushed,
            current_branch=lambda path: f"ticket/{path.name}",
            remove_worktree=lambda _repo, path: shutil.rmtree(path),
            delete_branch=lambda _repo, branch: branches.append(branch),
        ):
            _tidying(pages, "[runner]\nlog_retention_days = 0\n").tidy()
            gone = {name for name, path in places.items() if not path.exists()}
            assert gone == {"failed", "gone"}, gone
            assert sorted(branches) == [f"ticket/app-{tail[0]}", f"ticket/app-{tail[5]}"]
            # A ticket still in progress, and every one when it is turned off.
            again = _aged(root / "worktrees" / f"app-{tail[0]}", 40)
            _tidying(pages, "[runner]\nstale_worktree_days = 0\n").tidy(now=True)
            assert again.exists()
            # Nothing is guessed from a board that was not read.
            _tidying([]).tidy(now=True)
            assert again.exists()


@case
def a_low_disk_tidies_first_then_starts_nothing_and_leaves_the_ticket_in_ready():
    from ponos import resources

    runner = _tidying([])
    runner.dry_run = False
    runner._memory_warned, runner._disk_warned, runner._disk_tidied = False, False, 0.0
    runner.config.runner.min_free_memory_mb = 0
    runner.config.runner.min_free_disk_mb = 5000
    said: list[str] = []
    tidied: list[bool] = []
    runner.say = said.append
    runner.tidy = lambda now=False: tidied.append(now)
    runner._notify = lambda *args, **kwargs: said.append("notified")
    original = resources.disk_mb
    try:
        resources.disk_mb = lambda path: (1000, 100000)
        assert not runner.room_for_a_session() and not runner.room_for_a_session()
        assert tidied == [True], "one tidy, not one per place"
        assert sum("1000" in line for line in said) == 1 and "notified" in said, said
        resources.disk_mb = lambda path: (9000, 100000)
        assert runner.room_for_a_session()
        runner.config.runner.min_free_disk_mb = 0
        resources.disk_mb = lambda path: (1, 100000)
        assert runner.room_for_a_session(), "zero switches the guard off"
        # A tidy that freed the room is the whole answer: the ticket starts.
        runner.config.runner.min_free_disk_mb = 5000
        runner._disk_tidied = 0.0
        measures = iter([(1000, 100000), (8000, 100000)])
        resources.disk_mb = lambda path: next(measures)
        assert runner.room_for_a_session()
    finally:
        resources.disk_mb = original


@case
def a_worktree_is_made_without_the_excluded_folders_and_the_main_checkout_keeps_them():
    from ponos import git as git_module

    assert git_module.exclusions(" docs/media/, ,assets ") == ["docs/media", "assets"]
    with tempfile.TemporaryDirectory() as home:
        repo, path = Path(home) / "repo", Path(home) / "worktrees" / "site-9d2cb790"
        for step in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            assert git_module.git(step, repo.mkdir() or repo).ok if step[0] == "init" else git_module.git(step, repo).ok
        (repo / "docs" / "media").mkdir(parents=True)
        (repo / "docs" / "media" / "promo.mp4").write_text("big")
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("x")
        assert git_module.git(["add", "."], repo).ok
        assert git_module.git(["commit", "-qm", "first"], repo).ok
        git_module.add_worktree(repo, path, "ticket/x-9d2cb790", "main", ["docs/media"])
        assert (path / "src" / "a.py").exists() and not (path / "docs" / "media").exists()
        assert not git_module.is_dirty(path), "an excluded folder is not a deletion"
        assert (repo / "docs" / "media" / "promo.mp4").exists()
        assert git_module.git(["status", "--porcelain"], repo).out == ""
        other = Path(home) / "worktrees" / "site-aaaaaaaa"
        git_module.add_worktree(repo, other, "ticket/y-aaaaaaaa", "main")
        assert (other / "docs" / "media" / "promo.mp4").exists(), "nothing excluded, everything checked out"


@case
def the_console_measures_the_disk_and_cleans_only_between_runs():
    from ponos.web import api as web_api

    with _state_home() as root:
        _aged(root / "scratch" / "notes-1a2b3c4d", 30)
        console = web_api.Api.__new__(web_api.Api)
        console._config = _config("")
        console._stamp = web_api._mtime(console._config.path)
        console._runner = _tidying([_aged_page("page-1a2b3c4d", "Done", 30)])
        measured = console.disk()
        assert measured["sizes"]["scratch"] >= 1000 and measured["retention_days"] == 14
        with state.lock():
            try:
                console.clean()
            except RuntimeError as error:
                assert "run is in progress" in str(error)
            else:
                raise AssertionError("a tidy ran under a pass")
        cleaned = console.clean()
        assert cleaned["removed"] == 1 and cleaned["sizes"]["scratch"] == 0, cleaned



@case
def a_ticket_that_never_ran_gets_its_branch_drawn_fresh():
    made, commands = _worktree_for()
    assert voice.Voice().branch_note(made) == "", "nothing happened worth telling anyone about"
    assert not made.reused
    assert ["worktree", "add", "-b", "ticket/le-header-9d2cb790"] == commands[-1][:4]
    assert not any(command[:1] == ["rebase"] for command in commands)


@case
def a_branch_left_by_an_earlier_attempt_is_picked_up_and_replayed():
    """The failure this whole thing exists to stop.

    A branch is named after the ticket's ID, so every attempt asks for the same
    one: a session that failed, or a pull request nobody merged, used to leave a
    branch that refused that ticket for ever — “already exists — ticket already
    handled?” on every pass, until somebody ran `clean` by hand. It is checked
    out again and rebased onto the newest base instead.
    """
    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"), commits=2
    )
    assert made.reused, "the push that follows is not a fast-forward any more"
    note = voice.Voice().branch_note(made)
    assert "2 commit(s)" in note and "rebased onto `origin/main`" in note
    said = voice.Voice("fr").branch_note(made)
    assert said.startswith("La branche `ticket/le-header-9d2cb790` existait déjà"), said
    assert "rejouée sur `origin/main`" in said, "and the comment says it in its own voice"
    added = _one(commands, ["worktree", "add"])
    assert added[-1] == "ticket/le-header-9d2cb790", "checked out, not drawn again"
    assert "-b" not in added
    assert commands[-1] == ["rebase", "--autostash", "origin/main"]


@case
def a_branch_that_only_exists_on_origin_comes_back_with_its_commits():
    """A push that landed and a run that died after it: the work is on origin.

    Checking out a fresh branch of the same name would silently drop it — and
    the pull request open on it would sit there, describing commits nobody can
    see any more.
    """
    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/remotes/origin/ticket/le-header-9d2cb790"), commits=1
    )
    assert made.reused
    note = voice.Voice().branch_note(made)
    assert "it was pushed but never merged" in note
    added = _one(commands, ["worktree", "add"])
    assert added[:4] == ["worktree", "add", "--track", "-b"]
    assert added[-1] == "origin/ticket/le-header-9d2cb790"


@case
def a_worktree_kept_for_a_post_mortem_is_worked_in_again():
    """`keep_worktree_on_failure` leaves the directory *and* the branch in it.

    Nothing needs creating there — the branch is already checked out where the
    ticket wants it. Asking git for it again would only be told that it is.
    """
    from ponos import git as git_module

    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"),
        held_here=True,
        path_exists=True,
    )
    assert isinstance(made, git_module.Worktree) and made.reused
    note = voice.Voice().branch_note(made)
    assert "its worktree was still there" in note
    assert not any(command[:2] == ["worktree", "add"] for command in commands)
    assert commands[-1] == ["rebase", "--autostash", "origin/main"]


@case
def a_branch_held_by_another_worktree_is_never_taken_from_it():
    """The one case that still stops the ticket, and it should.

    Two runs of the same ticket at once, or a worktree kept somewhere else: what
    is in there is someone's work in progress, and moving its branch out from
    under it would break both. The message says where it is and how to let go.
    """
    from ponos import git as git_module

    made, _commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"),
        held="/somewhere/else",
    )
    assert isinstance(made, git_module.GitError)
    assert "/somewhere/else" in str(made) and "worktree remove" in str(made)


@case
def a_rebase_that_conflicts_is_undone_and_the_session_runs_anyway():
    """A conflict is not a reason to refuse the ticket a second time.

    The branch goes back to exactly what it was — an agent that opened on a
    half-applied rebase would spend its session resolving somebody else's merge
    — the session runs on it, and the comment says what it is behind on.
    """
    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"),
        commits=1,
        rebase="src/app.py",
    )
    assert made.reused
    note = voice.Voice().branch_note(made)
    assert "reused as it stands" in note and "src/app.py" in note
    assert commands[-1] == ["rebase", "--abort"], "nothing is left half-applied"


@case
def a_replay_still_happens_where_git_has_no_identity_of_its_own():
    """The CI runner, the container, the server nobody configured.

    A rebase writes commits, and git refuses to write one where it cannot tell
    who is writing. The replay failed there for that, the failure read as the
    branch refusing to move, and the ticket landed in Blocked saying the pull
    request would not merge — true, and not the reason. The identity is a
    fallback: a machine that has one of its own keeps committing under it.
    """
    from ponos import git as git_module

    with tempfile.TemporaryDirectory() as home:
        repo = Path(home) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)

        bare = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        with _patched_environ(bare):
            lent = git_module.identity(repo)
            assert lent["GIT_COMMITTER_EMAIL"], "a machine with no identity is lent one"
            assert lent["GIT_AUTHOR_NAME"] == lent["GIT_COMMITTER_NAME"]

            subprocess.run(
                ["git", "config", "user.email", "someone@example.invalid"], cwd=repo, check=True
            )
            assert git_module.identity(repo) == {}, "an identity of its own is left alone"


@contextmanager
def _patched_environ(values):
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@case
def a_repository_is_worked_under_the_account_its_owner_names():
    """Two GitHubs on one machine, and the command that goes out as the right one.

    Everything the runner asks `gh` about a repository — its name, its pull
    request, its merge — has to go out as the account that can see it. What
    designates it is the owner, read off whatever the caller has in hand: a
    remote, a pull request URL, or `owner/name` as a project page spells it.
    """
    from ponos import git as git_module

    for reference in (
        "https://github.com/Animalink/site/pull/12",
        "git@github.com:animalink/site.git",
        "https://github.com/animalink/site",
        "animalink/site",
    ):
        assert git_module.owner(reference) == "animalink", reference
    assert git_module.owner("site") == "", "a name alone designates no owner"

    asked: list[str] = []

    def token(account: str) -> str:
        asked.append(account)
        return f"gho-{account}" if account != "nobody" else ""

    accounts = {"animalink": "dev-animalink", "hermez-agency": "hermez-bot"}
    with _git_answering(account_token=token):
        assert git_module.token_for("animalink/site", accounts) == "gho-dev-animalink"
        assert git_module.token_for(
            "https://github.com/hermez-agency/x/pull/1", accounts
        ) == "gho-hermez-bot"
        # An owner nobody named, and a machine that names nobody: both are the
        # account `gh` is signed in as, which is what one GitHub always did.
        assert git_module.token_for("someone-else/x", accounts) == ""
        assert git_module.token_for("animalink/site", {}) == ""
        # And an account `gh` is not signed in as is not a ticket's problem:
        # `doctor` says so, the command runs as whoever is active.
        assert git_module.token_for("x/y", {"x": "nobody"}) == ""
    assert asked == ["dev-animalink", "hermez-bot", "nobody"], asked


@case
def a_gh_call_about_a_repository_carries_that_account_and_nothing_else():
    """The token reaches the command, and only through the environment.

    `GH_TOKEN` is what `gh` reads before anything on disk — and what the
    credential helper it installs reads too, which is how the push and the pull
    request that follows it go out as the same account.
    """
    from ponos import git as git_module

    seen: list[dict] = []

    class _Done:
        returncode, stdout, stderr = 0, "OPEN", ""

    def fake(args, cwd=None, capture_output=True, text=True, timeout=300, env=None):
        seen.append({"args": list(args), "env": env})
        return _Done()

    # `gh` is looked for before it is asked anything: a machine without it —
    # a CI runner, most of all — would otherwise skip the very call under test.
    original, original_which = git_module.subprocess.run, git_module.shutil.which
    git_module.subprocess.run = fake
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        with _git_answering(account_token=lambda account: "gho-secret"):
            git_module.pull_request_state(
                "https://github.com/animalink/site/pull/3", {"animalink": "dev-animalink"}
            )
            git_module.pull_request_state("https://github.com/x/y/pull/3", {})
    finally:
        git_module.subprocess.run = original
        git_module.shutil.which = original_which

    assert seen[0]["env"]["GH_TOKEN"] == "gho-secret"
    assert seen[0]["env"]["GITHUB_TOKEN"] == "gho-secret"
    assert "--json" in seen[0]["args"], seen[0]["args"]
    assert seen[1]["env"] is None, "no account named, no environment touched"


@case
def only_a_merge_a_rebase_could_answer_is_retried():
    """A refusal about the branch, told apart from a refusal about the work.

    A base branch that moved is what replaying answers. A check still red, a
    review still missing, a branch whose policy forbids this merge: pushing the
    branch again would spend a CI run to be refused in the same words.
    """
    from ponos import git as git_module

    for refusal in (
        "gh pr merge: Pull request is not mergeable: the merge commit cannot be cleanly created",
        "GraphQL: Base branch was modified. Review and try the merge again.",
        "the head branch is out of date",
    ):
        assert git_module.is_behind(refusal), refusal
    for refusal in (
        "gh pr merge: Pull request is not mergeable: the base branch policy prohibits the merge",
        "GraphQL: 1 approving review is required by reviewers with write access",
        "Required status check “ci” is expected",
    ):
        assert not git_module.is_behind(refusal), refusal


@case
def a_merge_refused_for_being_behind_is_replayed_and_asked_again():
    """The gesture you would make by hand, and nobody should make ten times a day.

    A pull request opened this morning is behind by noon on a repository that
    takes ten tickets a day. The refusal is about the branch, not about the
    work, so the branch is replayed onto its base, pushed, and the merge is
    asked once more — and the ticket says so rather than coming back as a
    question.
    """
    from ponos import git as git_module

    runner = _board_runner(
        [_reviewed("pbehind", "Validated", "https://github.com/x/y/pull/1")], {}
    )
    runner.config.runner.rebase = True
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    attempts: list[str] = []
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        if len(attempts) == 1:
            raise git_module.GitError("gh pr merge: Pull request is not mergeable")
        return "merged"

    def replay(repo, branch, onto, workdir, accounts=None, settle=None) -> str:
        replayed.append((repo, branch, onto))
        return ""

    with _state_home(), _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge), _git_answering(
        pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
        replay_pushed=replay,
    ):
        results = runner.deliver()

    assert len(attempts) == 2, "the merge was not asked again"
    assert replayed == [(Path("/repo"), "ticket/le-header-9d2cb790", "main")], replayed
    assert results[0]["status"] == "done", results
    said = runner.client.comments_written[-1]
    assert "replayed onto" in said, said


@case
def a_merge_refused_for_anything_else_is_still_a_question():
    """Nothing is pushed again to answer a review that has not happened."""
    from ponos import git as git_module

    runner = _board_runner(
        [_reviewed("preview", "Validated", "https://github.com/x/y/pull/1")], {}
    )
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        raise git_module.GitError("gh pr merge: 1 approving review is required")

    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge), _git_answering(
        replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
    ):
        results = runner.deliver()

    assert not replayed, "a review that has not happened is not a stale branch"
    assert results[0]["status"] == "blocked", results


@case
def a_replay_that_conflicts_leaves_the_merge_refused():
    """The branch goes back as it was, and the ticket asks rather than guesses."""
    from ponos import git as git_module

    runner = _board_runner(
        [_reviewed("pconflict", "Validated", "https://github.com/x/y/pull/1")], {}
    )
    # Resolution off: what is under test is the replay giving up, as it did
    # before conflicts were handed to a session — and as it still does then.
    runner.config.runner.resolve_conflicts = False
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    attempts: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        raise git_module.GitError("gh pr merge: Pull request is not mergeable")

    with _state_home(), _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge), _git_answering(
        pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
        replay_pushed=lambda *args, **kwargs: "CONFLICT (content): src/app.py",
    ):
        results = runner.deliver()

    assert len(attempts) == 1, "the merge is not asked again on a branch nothing moved"
    assert results[0]["status"] == "blocked", results


@case
def github_calling_a_pull_request_conflicting_is_heard_before_any_merge():
    """Asked first, rather than read in a refusal.

    A pull request GitHub already calls conflicting — or behind, on a
    repository that wants branches up to date — is replayed before the merge is
    asked at all: asking would only earn the refusal it has already announced.
    """
    from ponos import git as git_module

    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([_reviewed("pdirty", "Validated", url)], {})
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    attempts: list[str] = []
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        return "merged"

    with _state_home(), _github({url: "OPEN"}, merge=merge, blockers={url: "BEHIND"}), _git_answering(
        pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
        replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
    ):
        results = runner.deliver()

    assert len(replayed) == 1 and len(attempts) == 1, (replayed, attempts)
    assert results[0]["status"] == "done", results

    for refusal in (
        "gh pr merge: GraphQL: Pull Request has merge conflicts (mergePullRequest)",
        "gh pr merge: the head branch is not up to date with the base branch",
    ):
        assert git_module.is_behind(refusal), refusal


@case
def a_replay_that_conflicts_is_handed_to_a_session_rather_than_to_you():
    """The conflict takes a place, like a publication; a project left out asks.

    Nothing is merged and nothing is blocked while the column is read: the
    ticket is named for a session — `_carry_out` — and the pass runs it at the
    next free place. A project named in `resolve_conflicts_except` keeps the
    old answer: the ticket asks.
    """
    url = "https://github.com/x/y/pull/1"
    for left_out, expected in (("", "session"), ("Autre, site ", "blocked")):
        runner = _board_runner([_reviewed("pconflict", "Validated", url)], {})
        runner.config.runner.resolve_conflicts_except = left_out
        runner.under_reserve = lambda: 0.0
        runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))

        def merge(url: str, method: str = "squash", accounts=None) -> str:
            raise AssertionError("a pull request GitHub calls conflicting is not merged as is")

        with _state_home(), _github({url: "OPEN"}, merge=merge, blockers={url: "CONFLICTING"}), _git_answering(
            pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
            replay_pushed=lambda *args, **kwargs: "CONFLICT in src/app.py",
        ):
            settled, sessions = runner.delivering()

        if expected == "session":
            assert not settled, settled
            assert [ticket.id for ticket, _ in sessions] == ["pconflict"], sessions
        else:
            assert not sessions, sessions
            assert settled[0]["status"] == "blocked", settled
            assert "src/app.py" in runner.client.comments_written[-1]


@case
def a_base_that_keeps_moving_is_replayed_twice_then_asked_about():
    """Two replays, and then a question rather than a third.

    A repository merging every ten minutes can move its base between the push
    and the merge, every time. The runner replays, pushes, is refused again —
    leaves the ticket validated for the next pass — and on the second refusal
    stops chasing: the ticket asks, and says why.
    """
    from ponos import delivery

    url = "https://github.com/x/y/pull/1"
    page = _reviewed("pmoving", "Validated", url)
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        from ponos import git as git_module

        raise git_module.GitError("gh pr merge: Pull Request is not mergeable")

    with _state_home():
        passes = []
        for _ in range(3):
            runner = _board_runner([page], {"blocked": "Blocked"})
            runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
            with _github({url: "OPEN"}, merge=merge), _git_answering(
                pull_request_branches=lambda url, accounts=None: ("ticket/x-9d2cb790", "main"),
                replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
            ):
                passes.append(runner.deliver())
            if passes[-1]:
                break

    assert len(replayed) == delivery.MOST_REBASES == 2, replayed
    assert passes[0] == [], "the first refusal leaves it validated for the next pass"
    assert passes[-1][0]["status"] == "blocked", passes
    said = runner.client.comments_written[-1]
    assert "2 times" in said and "`main`" in said, said


@case
def a_base_moved_by_the_runners_own_merges_is_not_held_against_the_ticket():
    """Ten pull requests validated on one repository: the queue is not "a base that keeps moving".

    Each merge the runner makes leaves the others behind. Between two replays
    of this ticket the runner merged a sibling into the same repository, so the
    replay is owed to its own queue and the count starts again: the ticket is
    replayed a third time and merged, not blocked. With nothing merged by the
    runner in between, the limit holds — see the case above.
    """
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("pqueued", "Validated", url)
    replayed: list[tuple] = []
    refusals = ["not mergeable"] * 5

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        from ponos import git as git_module

        if refusals:
            raise git_module.GitError(f"gh pr merge: Pull Request is {refusals.pop()}")
        return "merged"

    with _state_home():
        runner = _board_runner([page], {"blocked": "Blocked"})
        runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
        passes = []
        for sibling in (2, 3, 4):
            with _github({url: "OPEN"}, merge=merge), _git_answering(
                pull_request_branches=lambda url, accounts=None: ("ticket/x-9d2cb790", "main"),
                replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
            ):
                passes.append(runner.deliver())
            if passes[-1]:
                break
            # A sibling of the same repository, merged by this runner meanwhile.
            runner._landed_in(f"https://github.com/x/y/pull/{sibling}")

    assert len(replayed) == 3, (replayed, passes)
    assert passes[-1][0]["status"] == "done", passes


def _reading_checks(
    verdicts: list[str], failing: list[list[str]], on_base: list[str], rerun: bool = True,
    unstarted: str = "",
):
    """`_checked` against a CI that answers `verdicts` in turn, and what it was asked."""
    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([], {})
    asked: list[str] = []
    verdicts, failing = list(verdicts), list(failing)

    def wait(url, worktree, minutes, accounts=None):
        asked.append("wait")
        return verdicts.pop(0)

    def again(url, accounts=None):
        asked.append("rerun")
        return rerun

    with _git_answering(
        wait_for_checks=wait,
        failing_checks=lambda url, accounts=None: failing.pop(0) if failing else [],
        unstarted_checks=lambda url, accounts=None: unstarted,
        rerun_failed_checks=again,
        failing_on=lambda url, base, accounts=None: asked.append(f"base {base}") or on_base,
    ):
        checks, said = runner._checked(url, Path("/work"), "main")
    return checks, said, asked


@case
def a_check_that_goes_green_once_run_again_is_a_flake_not_a_question():
    """The failed jobs are run again once, and the second verdict is the one kept."""
    checks, said, asked = _reading_checks(["failed", "passed"], [["frontend"]], [])
    assert checks == "passed", checks
    assert asked == ["wait", "rerun", "wait"], asked
    assert "`frontend`" in said and "flaky" in said, said

    checks, said, asked = _reading_checks(["passed"], [], [])
    assert (checks, asked) == ("passed", ["wait"]), "a green CI is not run again"


@case
def a_check_main_fails_too_is_the_bases_red_and_not_the_pull_requests():
    """Red twice, but red on the base as well: not the pull request's doing."""
    checks, said, asked = _reading_checks(
        ["failed", "failed"], [["frontend"], ["frontend"]], ["frontend", "core (3.11)"]
    )
    assert checks == "base-red", checks
    assert asked == ["wait", "rerun", "wait", "base main"], asked
    assert "`frontend`" in said and "`main`" in said, said


@case
def a_check_red_only_here_still_stops_the_merge_and_is_named():
    """The one red that is a question — and it says which checks, not “CI: red”."""
    checks, said, _ = _reading_checks(
        ["failed", "failed"], [["frontend"], ["core (3.11)", "frontend"]], ["frontend"]
    )
    assert checks == "failed", "one check red on main does not excuse another"
    assert "`core (3.11)`" in said and "`main`" in said, said

    # Nothing to run again (a check another app posts) and nothing gh can name:
    # red, as before — never green for want of knowing.
    checks, said, asked = _reading_checks(["failed"], [[]], ["frontend"], rerun=False)
    assert checks == "failed" and said == "CI: red.", (checks, said)
    assert asked == ["wait", "rerun"], asked


_NOT_STARTED = (
    "The job was not started because recent account payments have failed or your "
    "spending limit needs to be increased."
)


@case
def a_ci_github_never_started_is_said_as_such_and_not_run_again():
    """Red in two seconds, every job refused by GitHub's billing: nothing ran.

    It used to read “its checks fail” on every pull request of a private
    repository, and a forced merge stopped there without saying the one thing
    that mattered — not the code, the account. Running the jobs again would be
    refused the same way, so it is not asked.
    """
    checks, said, asked = _reading_checks(
        ["failed"], [["Tests", "Lint"]], [], unstarted=_NOT_STARTED
    )
    assert checks == "unstarted", checks
    assert asked == ["wait"], "neither run again nor compared with the base"
    assert "did not start" in said and "spending limit" in said, said


@case
def a_forced_merge_says_on_the_ticket_why_the_ci_stopped_it():
    """The sentence `_checked` wrote, not a generic “its checks fail”."""
    from types import SimpleNamespace

    url = "https://github.com/x/y/pull/1"
    for checks, sentence in (
        ("failed", "CI: red on `core (3.11)`, where `main` is not."),
        ("unstarted", f"CI: did not start — GitHub says: {_NOT_STARTED}"),
    ):
        runner = _board_runner([], {})
        runner._checked = lambda url, workdir, base, said=(checks, sentence): said
        job = SimpleNamespace(ticket=SimpleNamespace(id="p-forced"), workdir=Path("/work"), base="main")
        merges: list[str] = []
        with _state_home(), _github({}, merge=lambda *args, **kept: merges.append(args) or "merged"):
            why, later = runner._force_merge(job, url)
        assert (why, later, merges) == (sentence, False, []), (checks, why, later, merges)


@case
def an_older_gh_reads_the_checks_from_the_pull_request_itself():
    """`gh pr checks --json` is gh 2.48 and later; Ubuntu ships 2.46.

    Without the fallback every check read as unknown on such a machine — no
    names, nothing run again, no comparison with the base, and nothing the
    console could show — and a forced merge only ever said “its checks fail”.
    """
    from ponos import git as git_module

    rollup = {"statusCheckRollup": [
        {"__typename": "CheckRun", "name": "Tests", "status": "COMPLETED", "conclusion": "FAILURE",
         "detailsUrl": "https://github.com/x/y/actions/runs/38/job/116"},
        {"__typename": "CheckRun", "name": "Lint", "status": "COMPLETED", "conclusion": "SUCCESS",
         "detailsUrl": "https://github.com/x/y/actions/runs/38/job/117"},
        {"__typename": "CheckRun", "name": "Build", "status": "IN_PROGRESS", "conclusion": "",
         "detailsUrl": "https://github.com/x/y/actions/runs/38/job/118"},
        {"__typename": "StatusContext", "context": "GitGuardian", "state": "SUCCESS",
         "targetUrl": "https://dashboard.gitguardian.com"},
    ]}
    annotations = {"116": _NOT_STARTED, "117": ""}
    asked: list[list[str]] = []

    def run(args, *rest, **kept):
        asked.append(args)
        if args[:3] == ["gh", "pr", "checks"]:
            return git_module.Result(1, "", "unknown flag: --json\n\nUsage:  gh pr checks")
        if args[:3] == ["gh", "pr", "view"] and "statusCheckRollup" in args:
            return git_module.Result(0, json.dumps(rollup), "")
        if args[:2] == ["gh", "api"]:
            job = next(part for part in args if "check-runs/" in part).split("/")[-2]
            return git_module.Result(0, annotations.get(job, ""), "")
        return git_module.Result(1, "", "")

    original_which = shutil.which
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        with _git_answering(run=run, token_for=lambda reference, accounts=None: ""):
            url = "https://github.com/x/y/pull/1"
            listed = git_module.checks(url)
            assert [(one["name"], one["bucket"]) for one in listed] == [
                ("Tests", "fail"), ("Lint", "pass"), ("Build", "pending"), ("GitGuardian", "pass"),
            ], listed
            assert listed[0]["link"].endswith("/actions/runs/38/job/116"), listed[0]
            assert git_module.failing_checks(url) == ["Tests"]
            assert git_module.unstarted_checks(url) == _NOT_STARTED
            assert any("repos/x/y/check-runs/116/annotations" in part for one in asked for part in one)

            # One red check that did run is enough: that red is the code's.
            rollup["statusCheckRollup"][1]["conclusion"] = "FAILURE"
            assert git_module.unstarted_checks(url) == ""
    finally:
        git_module.shutil.which = original_which


def _forcing(checks: str, refuses: str = "", blocker: str = "", options=None):
    """`_force_merge` after a CI that said `checks`: what it answered, and the merges asked."""
    from types import SimpleNamespace

    from ponos import git as git_module

    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([], {}, options)
    runner._checked = lambda url, workdir, base: (checks, "")
    job = SimpleNamespace(ticket=SimpleNamespace(id="p-forced"), workdir=Path("/work"), base="main")
    merges: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        merges.append(url)
        if refuses:
            raise git_module.GitError(f"gh pr merge: {refuses}")
        return "merged"

    with _state_home(), _github({}, merge=merge, blockers={url: blocker} if blocker else {}):
        return runner._force_merge(job, url), merges


@case
def a_forced_merge_that_is_only_not_yet_is_left_to_the_validated_column():
    """Behind, conflicting, CI still running: postponed, never a question in review."""
    (why, later), merges = _forcing("passed", refuses="Head branch is out of date")
    assert later and "out of date" in why and len(merges) == 1, (why, later, merges)

    (why, later), merges = _forcing("pending", refuses="the base branch policy prohibits the merge")
    assert later and "still running" in why, (why, later)

    # GitHub already says so: not even asked.
    (why, later), merges = _forcing("passed", blocker="CONFLICTING")
    assert later and merges == [] and "conflicts with its base" in why, (why, later, merges)

    (why, later), _ = _forcing("passed")
    assert (why, later) == ("", False), "a merge that went through is not postponed"


@case
def a_forced_merge_that_is_a_question_still_waits_in_review():
    """Red here and only here, a rule of the branch, or no validated column to wait in."""
    (why, later), merges = _forcing("failed", blocker="BEHIND")
    assert not later and merges == [] and why == "its checks fail", (why, later, merges)

    (why, later), _ = _forcing("passed", refuses="the base branch policy prohibits the merge")
    assert not later and "policy" in why, (why, later)

    (why, later), merges = _forcing(
        "pending", refuses="Head branch is out of date", blocker="BEHIND",
        options=["In review", "Done"],
    )
    assert not later and len(merges) == 1, "without the column, nothing changes"


@case
def the_checks_gh_lists_are_read_into_names_and_runs_to_start_again():
    """`gh pr checks --json` and `gh run rerun`, as the runner asks them."""
    from ponos import git as git_module

    listed = [
        {"name": "frontend", "bucket": "fail",
         "link": "https://github.com/x/y/actions/runs/36840080436/job/110296847197"},
        {"name": "core (3.11)", "bucket": "pass",
         "link": "https://github.com/x/y/actions/runs/36840080436/job/110296847663"},
        {"name": "GitGuardian", "bucket": "fail", "link": "https://dashboard.gitguardian.com"},
    ]
    asked: list[list[str]] = []

    def run(args, *rest, **kept):
        asked.append(args)
        if args[:3] == ["gh", "pr", "checks"]:
            # Exit 1, as gh answers with a check red — and the list printed all the same.
            return git_module.Result(1, json.dumps(listed), "")
        if args[:2] == ["gh", "api"]:
            return git_module.Result(0, "frontend\nfrontend\n", "")
        return git_module.Result(0, "", "")

    original_which, original_sleep = shutil.which, git_module.time.sleep
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    git_module.time.sleep = lambda seconds: None
    try:
        with _git_answering(run=run, token_for=lambda reference, accounts=None: ""):
            url = "https://github.com/x/y/pull/1"
            assert git_module.failing_checks(url) == ["GitGuardian", "frontend"]
            assert git_module.rerun_failed_checks(url)
            assert ["gh", "run", "rerun", "36840080436", "--failed", "-R", "github.com/x/y"] in asked
            assert len([one for one in asked if one[:3] == ["gh", "run", "rerun"]]) == 1
            assert git_module.failing_on(url, "main") == ["frontend"]
            assert any("repos/x/y/commits/main/check-runs" in part for one in asked for part in one)
        with _git_answering(run=lambda *args, **kept: git_module.Result(1, "unknown flag: --json", "")):
            assert git_module.failing_checks("https://github.com/x/y/pull/1") == []
    finally:
        git_module.shutil.which = original_which
        git_module.time.sleep = original_sleep


_REPAIR_RUN = "https://github.com/x/y/actions/runs/7"


def _red_base(*, names=("frontend",)):
    """`gh`, answering that the newest commit of the base fails these checks."""
    return _git_answering(
        base_failures=lambda url, base, accounts=None: [(name, _REPAIR_RUN) for name in names],
        failing_on=lambda url, base, accounts=None: list(names),
    )


def _forced_on_red_base(runner, page, url):
    from types import SimpleNamespace

    runner._checked = lambda url, workdir, base: ("base-red", "")
    job = SimpleNamespace(
        ticket=ticket_module.Ticket(page),
        project=projects.Project("Site", Path("/repo")),
        workdir=Path("/work"),
        base="main",
    )
    merges: list[str] = []
    with _github({}, merge=lambda url, method="squash", accounts=None: merges.append(url)):
        return runner._force_merge(job, url), merges


@case
def a_red_base_sets_the_pull_request_aside_and_opens_one_repair_for_all_of_them():
    """Base red: no merge, no question, the card says so — and one ticket to repair it."""
    first, second = "https://github.com/x/y/pull/1", "https://github.com/x/y/pull/2"
    pages = [_reviewed("p1", "In progress", first), _reviewed("p2", "In progress", second)]
    with _state_home(), _red_base():
        runner = _board_runner(pages, {})
        (why, later), merges = _forced_on_red_base(runner, pages[0], first)
        assert later and merges == [] and "base is red" in why, (why, later, merges)
        assert state.waiting_for_base("p1") == ("main", first, ["frontend"])

        (why, later), merges = _forced_on_red_base(runner, pages[1], second)
        assert later and merges == [], (later, merges)
        assert state.waiting_for_base("p2")

    assert len(runner.client.created) == 1, runner.client.created
    title, values = runner.client.created[0]
    assert title == "Repair main of Site", title
    assert values["Status"] == "Ready" and values["Priority"] == 75, values
    assert "`frontend`" in runner.client.bodies[0] and _REPAIR_RUN in runner.client.bodies[0]


@case
def a_repair_that_is_done_is_followed_by_a_new_one_if_the_base_is_red_again():
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    with _state_home(), _red_base():
        runner = _board_runner([page], {})
        _forced_on_red_base(runner, page, url)
        runner.client._pages[-1].properties["Status"] = {"type": "status", "status": {"name": "Done"}}
        _forced_on_red_base(runner, page, url)
    assert len(runner.client.created) == 2, runner.client.created


@case
def a_green_base_with_a_red_pull_request_keeps_the_pull_request_blocked():
    """Base green, the red is the pull request's: today's behaviour, nothing set aside."""
    checks, said, _ = _reading_checks(["failed", "failed"], [["frontend"], ["frontend"]], [])
    assert checks == "failed", "red here and not on the base is still the pull request's"


def _repairing(heads: list[str], ok: bool = True, then: str = "passed", pushed: list | None = None):
    """`_mend` of a pull request red by its own fault: what it answered, and the sessions sent.

    `heads` is what the branch is on in turn — before the session, after it —
    and `then` what the CI says once the fix is pushed.
    """
    from types import SimpleNamespace

    from ponos import session as session_module

    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    runner = _board_runner([page], {})
    runner._body = lambda ticket: "Le titre est faux."
    runner._add_cost = lambda *args: None
    sessions: list[tuple] = []
    heads = list(heads)

    def work(job, template):
        sessions.append((job.body, template))
        return session_module.Outcome(
            ok=ok, blocked=not ok, session_id="s", summary="done" if ok else "unsure",
            log=Path("/log"), answer="- `settings.spec.ts` : locator exact\n\nRESULT: ok — x",
        )

    runner._run_session = work
    runner._checked = lambda url, workdir, base: (then, "CI: " + then)
    job = SimpleNamespace(
        ticket=ticket_module.Ticket(page), workdir=Path("/work"), base="main", branch="ticket/x",
    )
    job_copy = ticket_module.Job(
        ticket_module.Ticket(page), projects.Project("Site", Path("/repo")),
        branch="ticket/x", base="main", workdir=Path("/work"),
    )
    with _state_home(), _git_answering(
        head=lambda workdir: heads.pop(0) if len(heads) > 1 else heads[0],
        failing_checks=lambda url, accounts=None: ["frontend"],
        failed_log=lambda url, accounts=None, most=6000: "Error: locator resolved to 2 elements",
        pull_request_body=lambda url, accounts=None: "La PR.",
        rebasing=lambda workdir: False,
        is_dirty=lambda workdir: False,
        push_leased=lambda workdir, branch, was, accounts=None: pushed.append((branch, was)) or "",
        comment_pull_request=lambda *args, **kwargs: None,
    ):
        pushed = [] if pushed is None else pushed
        first = runner._mend(job_copy, url, "CI: red.")
        second = runner._mend(job_copy, url, "CI: red.") if len(heads) else None
    del job
    return first, second, sessions, pushed


@case
def a_pull_request_red_by_its_own_fault_is_repaired_by_a_session_and_goes_on():
    """The log reaches the session; its fix is pushed on the branch; a green CI lets the merge go on."""
    from ponos import prompt as prompt_module

    (checks, said, outcome), _, sessions, pushed = _repairing(["aaa", "bbb"], then="passed", pushed=[])
    assert checks == "passed" and outcome is not None, (checks, said)
    assert pushed == [("ticket/x", "aaa")], pushed
    assert len(sessions) == 1 and sessions[0][1] is prompt_module.REPAIR, sessions
    brief = sessions[0][0]
    assert "`frontend`" in brief and "locator resolved to 2 elements" in brief, brief
    assert "locator exact" in said and "réparé" in said or "repaired" in said, said


@case
def a_pull_request_still_red_after_its_repair_is_blocked_once_without_a_second_session():
    """Red again after the fix: `failed` is returned, and the same red never costs two sessions."""
    pushed: list = []
    (checks, said, _), _, sessions, _ = _repairing(["aaa", "bbb"], then="failed", pushed=pushed)
    assert checks == "failed" and "still red" in said, (checks, said)
    assert len(sessions) == 1

    # The head the repair pushed, and the one it started from, are both spent.
    runner_heads = ["aaa", "bbb"]
    (_, _, _), second, sessions, _ = _repairing(["aaa", "bbb", "bbb"], then="failed", pushed=[])
    assert second is not None and second[0] == "failed" and second[2] is None, second
    assert len(sessions) == 1, "a second session was sent after the same red"
    del runner_heads


@case
def a_repair_that_answers_blocked_or_commits_nothing_pushes_nothing():
    (checks, said, outcome), _, sessions, pushed = _repairing(["aaa"], ok=False, pushed=[])
    assert checks == "failed" and outcome is not None and not pushed, (checks, pushed)
    assert "unsure" in said and "locator exact" in said, said

    (checks, said, _), _, sessions, pushed = _repairing(["aaa"], ok=True, pushed=[])
    assert checks == "failed" and not pushed and "committed nothing" in said, (said, pushed)


@case
def the_repair_attempts_of_a_ticket_are_kept_by_head_commit():
    with _state_home():
        assert not state.mended("p1", "aaa")
        state.mending("p1", "aaa")
        assert state.mended("p1", "aaa") and not state.mended("p1", "bbb")
        assert not state.mended("p2", "aaa")
        state.forget_mending("p1", "aaa")
        assert not state.mended("p1", "aaa")


@case
def a_pull_request_set_aside_waits_for_a_green_base_then_goes_on_its_own():
    """Still red: left alone, no merge asked. Green again: merged, and the card says so."""
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "Validated", url)
    merges: list[str] = []

    def merge(url, method="squash", accounts=None):
        merges.append(url)
        return "merged"

    with _state_home():
        state.wait_for_base("p1", "main", url, ["frontend"])
        runner = _board_runner([page], {})
        with _github({url: "OPEN"}, merge=merge), _git_answering(
            failing_on=lambda url, base, accounts=None: ["frontend", "lint"]
        ):
            assert runner.deliver() == [] and merges == []
            assert runner.client.comments_written == [], "waiting is not said again at every pass"
        with _github({url: "OPEN"}, merge=merge), _git_answering(
            failing_on=lambda url, base, accounts=None: []
        ):
            done = runner.deliver()
        assert merges == [url] and done[0]["status"] == "done", (merges, done)
        assert state.waiting_for_base("p1") is None
    assert any("green again" in text for text in runner.client.comments_written)


@case
def a_resolved_pull_request_on_a_red_base_goes_back_to_validated_without_a_question():
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    with _state_home(), _red_base():
        runner = _board_runner([page], {})
        done = runner._left_for_base(
            ticket_module.Ticket(page), projects.Project("Site", Path("/repo")), url, "main", "record"
        )
        assert state.waiting_for_base("p1")
    assert done["status"] == "waiting" and done["reason"] == "merge.base-red", done
    status = [values["Status"] for _, values in runner.client.written if "Status" in values]
    assert status == ["Validated"], status
    assert "the base is red, it is not this pull request" in runner.client.comments_written[-1]
    assert "Repair main of Site" in runner.client.comments_written[-1]


@case
def the_failures_of_a_base_and_its_ci_at_push_are_read_from_gh():
    from ponos import git as git_module

    def answering(out, ok=True):
        return lambda args, *rest, **kept: git_module.Result(0 if ok else 1, out, "")

    original_which = shutil.which
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        url = "https://github.com/x/y/pull/1"
        with _git_answering(
            run=answering("frontend\thttps://github.com/x/y/runs/1\nlint\t"),
            token_for=lambda reference, accounts=None: "",
        ):
            assert git_module.base_failures(url, "main") == [
                ("frontend", "https://github.com/x/y/runs/1"), ("lint", "")
            ]
        repo = Path("/repo")
        for out, wanted in (
            ("[]", "none"),
            ('[{"conclusion": "skipped"}, {"conclusion": "skipped"}]', "skipped"),
            ('[{"conclusion": "skipped"}, {"conclusion": "failure"}]', "ran"),
            ("not json", ""),
        ):
            with _git_answering(
                run=answering(out),
                remote_url=lambda repo: "git@github.com:x/y.git",
                token_for=lambda reference, accounts=None: "",
            ):
                assert git_module.ci_at_push(repo, "main") == wanted, (out, wanted)
        with _git_answering(run=answering("", ok=False), remote_url=lambda repo: "git@github.com:x/y.git",
                            token_for=lambda reference, accounts=None: ""):
            assert git_module.ci_at_push(repo, "main") == "", "a question GitHub did not answer"
    finally:
        git_module.shutil.which = original_which


@case
def doctor_says_when_a_base_has_no_ci_at_push():
    from ponos import __main__ as cli

    with _git_answering(default_branch=lambda repo: "dev", ci_at_push=lambda repo, base, accounts=None: "none"):
        assert "dev has no CI run at push" in cli._base_without_ci(Path("/repo"))
    with _git_answering(default_branch=lambda repo: "dev", ci_at_push=lambda repo, base, accounts=None: "skipped"):
        assert "only skipped" in cli._base_without_ci(Path("/repo"))
    for found in ("ran", ""):
        with _git_answering(default_branch=lambda repo: "dev", ci_at_push=lambda repo, base, accounts=None: found):
            assert cli._base_without_ci(Path("/repo")) == ""


@case
def a_resolution_report_is_what_the_session_wrote_above_its_verdict():
    from ponos import delivery

    answer = "- `a.py` : les deux gardés\nTests : verts.\n\n**RESULT: ok — résolu**"
    assert delivery._report_of(answer) == "- `a.py` : les deux gardés\nTests : verts."
    assert delivery._report_of("RESULT: ok — rien à dire") == ""


@case
def conflicts_are_resolved_everywhere_but_where_the_file_says_not():
    config = _config('[runner]\nresolve_conflicts_except = ["Animalink", "Site vitrine"]\n')
    assert config.runner.resolve_conflicts_except == "Animalink, Site vitrine"
    assert not config.runner.resolves_conflicts("site vitrine")
    assert config.runner.resolves_conflicts("Trader IA")
    assert _config('[runner]\nresolve_conflicts_except = "Site"\n').runner.resolve_conflicts_except == "Site"
    off = _config("[runner]\nresolve_conflicts = false\n").runner
    assert not off.resolves_conflicts("Trader IA")
    assert _config("[runner]\nchecks_timeout_minutes = -3\n").runner.checks_timeout_minutes == 0


@case
def a_directory_holding_work_is_not_cleared_to_make_room():
    """Uncommitted changes under the ticket's path outrank the ticket."""
    from ponos import git as git_module

    made, _commands = _worktree_for(commits=0, dirty=True, path_exists=True)
    assert isinstance(made, git_module.GitError)
    assert "still holds work" in str(made) and "clean --force" in str(made)


@case
def a_residue_that_cannot_be_deleted_is_moved_aside_and_the_worktree_is_made():
    """Files a container made as root: no right to delete them, still a ticket to run."""
    from ponos import git as git_module

    original = (git_module.shutil.rmtree, git_module.shutil.which)
    with tempfile.TemporaryDirectory() as home:
        root = Path(home)
        os.environ["XDG_STATE_HOME"] = str(root / "state")
        path = root / "worktrees" / "leadz-9d2cb790"
        (path / "vendor" / "lib").mkdir(parents=True)
        (path / "vendor" / "lib" / "a.php").write_text("x")
        (path / "vendor").chmod(0o500)  # nothing in it can be unlinked, as non-root
        try:
            # The deletion refused whatever the user is, and no Docker to ask.
            git_module.shutil.rmtree = lambda *_args, **_kept: None
            git_module.shutil.which = lambda _name: None
            aside = git_module.discard(path)
            assert not path.exists() and Path(aside).is_dir()
            assert Path(aside).parent == root / "state" / "ponos" / "leftovers"
            # Nothing but a directory git cannot be asked about: a fresh one is made.
            path.mkdir()
            made, _commands = _worktree_for(commits=0, path_exists=True)
            assert not isinstance(made, git_module.GitError)
        finally:
            git_module.shutil.rmtree, git_module.shutil.which = original
            os.environ.pop("XDG_STATE_HOME", None)
            for directory, _names, _files in os.walk(root):
                os.chmod(directory, 0o700)


@case
def a_residue_is_emptied_by_a_container_when_docker_is_there():
    from ponos import git as git_module

    sent: list[list[str]] = []
    original = (git_module.shutil.rmtree, git_module.shutil.which, git_module.run)
    with tempfile.TemporaryDirectory() as home:
        path = Path(home) / "leadz-9d2cb790"
        path.mkdir()
        (path / "var").mkdir()

        def docker(args, *_rest, **_kept):
            sent.append(list(args))
            original[0](path / "var")
            return git_module.Result(0, "", "")

        try:
            git_module.shutil.rmtree = lambda *_args, **_kept: None
            git_module.shutil.which = lambda _name: "/usr/bin/docker"
            git_module.run = docker
            assert git_module.discard(path) == ""
        finally:
            git_module.shutil.rmtree, git_module.shutil.which, git_module.run = original
        assert not path.exists()
    assert sent and sent[0][:2] == ["docker", "run"] and "sh" not in sent[0] and "-c" not in sent[0]
    assert sent[0][-5:] == ["find", "/w", "-mindepth", "1", "-delete"]


@case
def a_directory_with_a_git_is_never_a_residue():
    from ponos import git as git_module

    with tempfile.TemporaryDirectory() as home:
        worktrees = Path(home) / "worktrees"
        (worktrees / "real-11111111").mkdir(parents=True)
        (worktrees / "real-11111111" / ".git").write_text("gitdir: /elsewhere")
        (worktrees / "left-22222222" / "vendor").mkdir(parents=True)
        assert git_module.residues(worktrees) == [worktrees / "left-22222222"]
        assert git_module.discard(worktrees / "real-11111111") == ""
        assert (worktrees / "real-11111111" / ".git").exists()


@case
def clean_removes_a_residue_and_leaves_a_real_worktree():
    from ponos import __main__ as cli

    with tempfile.TemporaryDirectory() as home:
        root = Path(home)
        repo, worktrees = root / "repo", root / "ponos" / "worktrees"
        repo.mkdir()
        for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                cwd=repo, check=True, capture_output=True,
            )
        real = worktrees / "real-11111111"
        worktrees.mkdir(parents=True)
        subprocess.run(["git", "worktree", "add", "-q", str(real)], cwd=repo, check=True, capture_output=True)
        (worktrees / "left-22222222" / ".phpunit.cache").mkdir(parents=True)
        kept = cli._clear_residues(sorted(worktrees.iterdir()))
        assert not (worktrees / "left-22222222").exists()
        assert (real / ".git").exists() and kept == [real]


@case
def only_a_replayed_branch_is_ever_force_pushed():
    """A rebase rewrites what origin already has, so the push stops being a

    fast-forward — and a ticket that came back with “the push was refused” for
    doing exactly what it was told to do would be the same dead end one step
    later. `--force-with-lease`, never `--force`: origin moving under us is
    still a refusal.
    """
    from ponos import git as git_module

    sent: list[list[str]] = []

    def fake(args, cwd, timeout=300, token=""):
        sent.append(list(args))
        return git_module.Result(0, "", "")

    with _git_answering(git=fake):
        git_module.push(Path("/nowhere"), "ticket/le-header-9d2cb790")
        git_module.push(Path("/nowhere"), "ticket/le-header-9d2cb790", force=True)
    # Only the pushes: a push also asks the worktree which remote it is on, to
    # know which GitHub account it goes out under.
    pushes = [args for args in sent if args[0] == "push"]
    assert "--force-with-lease" not in pushes[0]
    assert "--force-with-lease" in pushes[1] and "--force" not in pushes[1]


# -- releases ----------------------------------------------------------------


@case
def the_version_and_the_changelog_never_drift():
    """The one invariant the whole release system rests on.

    `__version__` and the newest released section of CHANGELOG.md are written by
    the same command, in the same breath. If they are ever seen apart, something
    edited one of them by hand — and the release that follows would ship a
    number whose notes describe a different one.
    """
    version = release.read_version()
    release.parse(version)  # raises if it is not a version at all

    entries = release.released(release.CHANGELOG.read_text(encoding="utf-8"))
    for name, date, body in entries:
        release.parse(name)
        assert date, f"[{name}] has no date"
        assert body.strip(), f"[{name}] has no notes"

    order = [release.order(name) for name, _date, _body in entries]
    assert order == sorted(order, reverse=True), "the changelog runs newest first"

    if entries:
        assert entries[0][0] == version, (
            f"__version__ is {version}, the newest changelog section is [{entries[0][0]}]"
        )


@case
def the_dokploy_template_pins_the_image_of_this_version():
    """Never `latest`: the image the tag of this tree publishes, and `bump` moves it."""
    version = release.read_version()
    assert release.read_pins() == {"docker-compose.yml": version, "meta.json": version}

    copy = Path(tempfile.mkdtemp())
    for name in release.PINS:
        shutil.copy(release.BLUEPRINT / name, copy / name)
    release.write_pins("9.8.7", copy)
    assert release.read_pins(copy) == {"docker-compose.yml": "9.8.7", "meta.json": "9.8.7"}
    assert json.loads((copy / "meta.json").read_text(encoding="utf-8"))["version"] == "9.8.7"


@case
def the_dokploy_template_keeps_to_the_catalogues_rules():
    """What Dokploy/templates refuses, and the variables both files must agree on."""
    import tomllib

    compose = (release.BLUEPRINT / "docker-compose.yml").read_text(encoding="utf-8")
    template = tomllib.loads((release.BLUEPRINT / "template.toml").read_text(encoding="utf-8"))
    meta = json.loads((release.BLUEPRINT / "meta.json").read_text(encoding="utf-8"))

    for refused in ("ports:", "container_name", "networks:", ":latest"):
        assert refused not in compose, f"{refused} is not allowed in a Dokploy template"
    assert re.search(r"^services:\n  ponos:$", compose, re.MULTILINE), "the service is the folder's name"
    assert [domain["serviceName"] for domain in template["config"]["domains"]] == [meta["id"]] == ["ponos"]
    assert template["config"]["domains"][0]["port"] == 8787
    assert (release.BLUEPRINT / meta["logo"]).is_file()
    # An array of `KEY=value` strings: the catalogue's AGENTS.md refuses the table form.
    entries = template["config"]["env"]
    assert isinstance(entries, list), "env is an array of strings, not a table"
    env = dict(entry.split("=", 1) for entry in entries)
    given = set(env)
    read = set(re.findall(r"\$\{(\w+)\}", compose))
    assert given == read, (given ^ read)
    secrets = {"PONOS_WEB_PASSWORD", "PONOS_WEB_TOKEN"}
    assert all(env[name].startswith("${") for name in secrets), "generated, never written"
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GH_TOKEN", "PONOS_NOTION_TOKEN"):
        assert env[name] == "", f"{name} is the user's to give"


@case
def a_release_only_ever_moves_forward():
    assert release.next_version("0.1.0", "patch") == "0.1.1"
    assert release.next_version("0.1.9", "minor") == "0.2.0"
    assert release.next_version("0.9.3", "major") == "1.0.0"
    assert release.next_version("1.2.3", "2.0.0") == "2.0.0"

    for backwards in ("0.1.0", "1.2.2", "1.0.0"):
        try:
            release.next_version("1.2.3", backwards)
        except release.Problem:
            pass
        else:
            raise AssertionError(f"{backwards} after 1.2.3 must be refused")

    # Once, in a repository's life: nothing released yet, so the number the tree
    # already carries is the number to release it under.
    assert release.next_version("0.1.0", "0.1.0", first=True) == "0.1.0"


@case
def a_bump_promotes_the_notes_and_opens_an_empty_unreleased():
    text = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n\n"
        "## [0.1.0] - 2026-01-01\n\n### Added\n\n- The first thing.\n"
    )
    moved = release.promote(text, "0.2.0", "2026-08-31")

    names = [name for name, _date, _body in release.sections(moved)]
    assert names == ["Unreleased", "0.2.0", "0.1.0"], names

    assert release.notes_for(moved, "0.2.0") == "### Added\n\n- A thing."
    assert release.notes_for(moved, "0.1.0") == "### Added\n\n- The first thing."
    unreleased = dict((name, body) for name, _date, body in release.sections(moved))
    assert unreleased["Unreleased"].strip() == "", "the next cycle starts empty"


@case
def an_empty_unreleased_is_not_a_release():
    """A tag with no notes is a tag, and nobody came here for a tag."""
    for refused in (
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n- One.\n",
        "# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- One.\n",
    ):
        try:
            release.promote(refused, "0.2.0", "2026-08-31")
        except release.Problem:
            pass
        else:
            raise AssertionError("an empty or missing [Unreleased] must be refused")

    already = "# Changelog\n\n## [Unreleased]\n\n- New.\n\n## [0.2.0] - 2026-01-01\n\n- Old.\n"
    try:
        release.promote(already, "0.2.0", "2026-08-31")
    except release.Problem:
        pass
    else:
        raise AssertionError("a version that already has a section must be refused")


@case
def the_dash_in_a_changelog_heading_is_whichever_one_was_typed():
    """The file is written by hand, and a hand that writes em dashes writes them here.

    A heading the parser fails to see is a release whose notes silently come out
    empty, which is only noticed once it is published.
    """
    for dash in ("-", "\u2013", "\u2014"):
        text = f"# Changelog\n\n## [0.1.0] {dash} 2026-01-01\n\n- One.\n"
        assert release.notes_for(text, "0.1.0") == "- One.", dash


def _plain(text: str) -> str:
    """The same output a pipe would get: colour is not part of what is asserted."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


@case
def a_bare_command_line_presents_the_product_and_its_version():
    """`ponos`, typed alone, is somebody's first look at what they installed.

    So it answers the two questions that come with that — what is this, and
    which version am I on — before it lists the verbs. The frame is drawn from
    the uncoloured text, which is what keeps it square once colours are on.
    """
    with _state_home():
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            assert cli_main([]) == 0
        printed = _plain(buffer.getvalue())

    assert f"Ponos {__version__}" in printed
    assert "Turns ready Notion tickets into Claude Code sessions." in printed
    for name in subcommands():
        assert f"\n    {name} " in printed or f"\n    {name}  " in printed, (
            f"{name} is a command the welcome screen does not name"
        )

    framed = [line for line in _plain(banner()).splitlines() if line.strip()]
    assert len({len(line) for line in framed}) == 1, "the frame is not square"


@case
def a_waiting_update_is_said_on_the_welcome_screen():
    """The one thing worth adding to a version number: that it is not the newest.

    Read from the stamp a run already wrote — a welcome screen that fetched
    would be a network round trip for every `ponos` typed by mistake.
    """
    with _state_home():
        update.remember(update.Status(current="a" * 40, latest="b" * 40))
        assert "b" * 8 in _plain(banner())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            welcome(build_parser())
        assert "ponos update" in _plain(buffer.getvalue())


@case
def the_console_header_and_the_command_line_agree_on_the_version():
    """One number, two surfaces: what --version prints is what the browser shows.

    The console reads it bare — an update waiting is a separate field, so the
    header can print a version where a version belongs rather than a sentence.
    It follows the number with the commit it runs, read from git: between two
    releases every commit ran under the same number, and only the commit says
    which code answers.
    """
    with _state_home():
        running = update.running()
        number, _, short = running["version"].partition("+")
        assert number == __version__ and len(short) >= 7 and _head(ROOT).startswith(short), running
        assert running["commit"] == _head(ROOT), "the tooltip names another commit"
        assert running["date"] and running["subject"], "the tooltip has nothing to say"
        assert web_api._update_available() == "", "nothing checked yet is not an update"
        # Compared against what is on disk: the stamp has to be about this checkout.
        update.remember(update.Status(current=_head(ROOT), latest="b" * 40))
        assert web_api._update_available() == "b" * 8


@case
def a_copy_that_is_not_a_repository_says_its_number_alone():
    """No `.git` beside the sources — a copy, an image: the number, and no commit."""
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "app"
        shutil.copytree(ROOT / "src", copy / "src", ignore=shutil.ignore_patterns("__pycache__"))
        said = subprocess.run(
            [sys.executable, "-c", "import json; from ponos import update; print(json.dumps(update.running()))"],
            env={**os.environ, "PYTHONPATH": str(copy / "src")}, cwd=scratch,
            capture_output=True, text=True, check=True,
        ).stdout
    assert json.loads(said) == {"version": __version__, "commit": "", "date": "", "subject": ""}, said


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/ponos/web/static"
FRONTEND = ROOT / "frontend"


def _shipped() -> list[Path]:
    """Every file the console hands a browser, as it sits in the package.

    `frontend/` is the source; this is the build, and the build is what is
    committed — the installer is a `git clone` onto a machine that has python3
    and git and no reason to have Node.
    """
    return [STATIC / "index.html", *sorted((STATIC / "assets").glob("*"))]


def _built(extension: str) -> Path:
    """The console's own file of that kind, whatever hash the build gave it."""
    found = sorted((STATIC / "assets").glob(f"console-*.{extension}"))
    assert len(found) == 1, f"one console.{extension} expected, the build left {found}"
    return found[0]


@case
def the_console_ships_its_built_bundle():
    """A clone of this repository is a console that opens, with nothing built.

    `ponos` installs by cloning and running `python3`. If the bundle
    lived only in `frontend/` and were built on the way in, the install would
    need Node — which is exactly the dependency this tool exists without.
    """
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    bundle, style = _built("js"), _built("css")
    # The names are hashed, so the page is what says which build it is: a file
    # it names that is not in the package is a console that opens blank.
    assert f"/static/assets/{bundle.name}" in page, "the page does not load the bundle"
    assert f"/static/assets/{style.name}" in page, "the page does not load the stylesheet"
    for named in re.findall(r'"/static/(assets/[^"]+)"', page):
        assert (STATIC / named).is_file(), f"the page names a file the build did not write: {named}"
    assert (FRONTEND / "package.json").is_file(), "the source the bundle is built from is gone"
    assert (FRONTEND / "components.json").is_file(), "shadcn/ui is no longer configured"


@case
def the_console_is_downloaded_once_and_compressed():
    """A second load fetches the page and nothing else; the first, gzipped.

    On 1 October 2026 every load of the console downloaded 1.3 MB again: every
    file was `no-store`, nothing was compressed, and the names were fixed, so
    nothing could have been kept safely either. The names now change with what
    the files hold, so `assets/` is kept for a year and `index.html` — the one
    file that says which names are current — is never kept at all.
    """
    import urllib.request

    from ponos.web import server as web_server

    api = _bare_api(_TalkClient([]))
    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def get(path: str, **headers: str):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", headers={"Authorization": "Bearer tok", **headers}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.headers, response.read()

    bundle = _built("js")
    try:
        headers, _ = get("/")
        assert headers["Cache-Control"] == "no-store", "the page that names the build was kept"
        headers, body = get(f"/static/assets/{bundle.name}", **{"Accept-Encoding": "gzip, br"})
        assert "immutable" in headers["Cache-Control"] and "max-age=31536000" in headers["Cache-Control"]
        assert headers["Content-Encoding"] == "gzip" and headers["Vary"] == "Accept-Encoding"
        assert gzip.decompress(body) == bundle.read_bytes(), "gzipped is not the same file"
        assert int(headers["Content-Length"]) == len(body) < bundle.stat().st_size / 2
        headers, body = get(f"/static/assets/{bundle.name}")
        assert headers["Content-Encoding"] is None and body == bundle.read_bytes(), (
            "a client that never asked for gzip got it"
        )
        headers, _ = get(f"/static/assets/{bundle.name}", **{"Accept-Encoding": "gzip;q=0"})
        assert headers["Content-Encoding"] is None, "q=0 means never"
    finally:
        console.shutdown()
        console.server_close()

    # What the first load fetches — the page, the bundle and what it preloads,
    # the stylesheet and the icon — under the 500 kB the ticket set, gzipped.
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    first = [STATIC / "index.html"] + [
        STATIC / named for named in re.findall(r'"/static/(assets/[^"]+)"', page)
    ]
    weight = sum(len(gzip.compress(path.read_bytes(), compresslevel=9)) for path in first)
    assert weight < 500_000, f"the first load is {weight // 1000} kB compressed"


@case
def the_console_is_installable_as_an_app():
    """A manifest, three icons and a worker, served to a browser with no cookie.

    A browser fetches the manifest and the worker for itself, and a manifest
    request leaves without the cookie unless the page says `use-credentials` —
    so these answer to nobody in particular, and what they answer is whole: every
    icon the manifest names is a file of the build, the worker is served from
    `/` so that it may control `/`, and it is never kept, or an installed app
    would stay on the build it was installed with.
    """
    import json
    import urllib.error
    import urllib.request

    from ponos.web import server as web_server

    api = _bare_api(_TalkClient([]))
    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def get(path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.headers, response.read()

    try:
        headers, body = get("/static/manifest.webmanifest")
        assert headers["Content-Type"].startswith("application/manifest+json")
        manifest = json.loads(body)
        assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
        assert manifest["name"] and manifest["short_name"]
        sizes = {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]}
        assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
        for icon in manifest["icons"]:
            headers, data = get(icon["src"])
            assert headers["Content-Type"] == "image/png" and data.startswith(b"\x89PNG")
        headers, body = get("/sw.js")
        assert headers["Content-Type"].startswith("application/javascript") or headers[
            "Content-Type"
        ].startswith("text/javascript")
        assert headers["Cache-Control"] == "no-store", "an installed app would never see a new build"
        assert b"__BUILD__" not in body, "the worker was shipped as a template"
        get("/static/offline.html")
        # And the console itself is still behind its key.
        try:
            get("/api/board")
            raise AssertionError("the board answered without a key")
        except urllib.error.HTTPError as error:
            assert error.code == 401
    finally:
        console.shutdown()
        console.server_close()

    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in page and 'crossorigin="use-credentials"' in page


@case
def the_console_and_the_landing_page_draw_one_robot():
    """The mascot is one file, and the console bundles it rather than a copy.

    The landing page loads `docs/mascot/ponos-robot.js` from a <script>
    tag; the console imports that very module through Vite, and takes its
    favicon from the same directory. A second copy of the drawing would be a
    robot that changes on one page and not on the other.
    """
    mascot = ROOT / "docs/mascot/ponos-robot.js"
    assert mascot.is_file(), "the mascot's one source is gone"
    copies = [
        path
        for path in ROOT.rglob("ponos-robot.js")
        if "node_modules" not in path.parts and path != mascot
    ]
    assert not copies, f"a copy of the mascot: {copies}"
    robot = (FRONTEND / "src/components/console/robot.tsx").read_text(encoding="utf-8")
    assert '"@mascot/ponos-robot.js"' in robot, "the console draws a robot of its own"
    vite = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    assert '"../docs/mascot"' in vite, "@mascot no longer points at the landing page's file"
    page = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "../docs/mascot/favicon.svg" in page, "the console's favicon is not the mascot's"
    source = mascot.read_text(encoding="utf-8")
    assert "waiting:" in source, "a ticket waiting on a person has no face of its own"
    assert "'still'" in source, "a board of robots cannot hold them still"


LANDING = ROOT / "docs/index.html"


@case
def the_console_and_the_landing_page_share_one_set_of_tokens():
    """One file of colours, faces and radius, and the site has no other.

    The console imports `frontend/src/tokens.css`; the site has no build step,
    so it links `docs/tokens.css`, which `npm run build` copies. A copy that
    drifts is two identities again — and the site's own stylesheet naming a
    colour of its own is the same drift, written by hand.
    """
    source = (FRONTEND / "src/tokens.css").read_text(encoding="utf-8")
    copy = (ROOT / "docs/tokens.css").read_text(encoding="utf-8")
    assert copy == source, "docs/tokens.css is stale — run npm run build in frontend/ and commit it"
    for name in ("--primary", "--background", "--radius", "--tr-green", "--series-1", "--sans", "--mono", "--heading"):
        assert f"{name}:" in source, f"{name} is not among the tokens"
    assert ".dark {" in source, "the tokens have no dark theme"
    index = (FRONTEND / "src/index.css").read_text(encoding="utf-8")
    assert '@import "./tokens.css";' in index, "the console no longer reads the tokens"
    assert "--primary:" not in index, "the console declares a colour outside the tokens"
    vite = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    assert '"../docs/tokens.css"' in vite, "the build no longer publishes the tokens for the site"

    page = LANDING.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="tokens.css">' in page, "the site does not load the tokens"
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    stray = re.findall(r"#[0-9a-fA-F]{3,8}\b", style)
    assert not stray, f"the site names colours of its own: {stray}"
    for gone in ("Inter", "Instrument Serif", "#3b82f6"):
        # A whole word: `IntersectionObserver` is not the old face.
        assert not re.search(rf"(?<!\w){re.escape(gone)}(?!\w)", page), f"{gone} is the old identity"
    assert "family=Bricolage+Grotesque" in page, "the site does not load the headings' face"
    for gone in ("DM+Sans", "JetBrains+Mono"):
        assert gone not in page, f"{gone} is the old identity"
    assert "ponos-theme" in page and "prefers-color-scheme" in page, "the site has no light and dark"


@case
def the_landing_page_opens_on_ponos_and_tells_the_loop_in_seven_sections():
    """Seven sections at most, the first one Ponos and the promise.

    Seventeen sections at the same level is a manual, and the manual is the
    README: the site says the promise, the four kinds of task, the loop and
    three proofs, the console, the integrations — Notion among them, not
    before them —, the install and who made it, and links the rest.
    """
    page = LANDING.read_text(encoding="utf-8")
    sections = re.findall(r"<section\b[^>]*>", page)
    assert 0 < len(sections) <= 7, f"{len(sections)} sections — the site is a manual again"
    hero = page.split("<section", 2)[1]
    assert 'id="top"' in hero.split(">", 1)[0], "the page does not open on its hero"
    assert "<ponos-robot" in hero and "Ponos" in hero, "Ponos is not on the first screen"
    assert "Write the ticket." in hero and "It comes back done." in hero, "the promise is not the headline"
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert "Write the ticket. It comes back done." in title
    assert "Notion" not in title and "Claude" not in title, "the promise leans on somebody else's brand"
    description = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
    assert "It comes back done." in description
    assert "It comes back done." in re.search(r'<meta property="og:title" content="([^"]*)"', page).group(1)
    assert "It comes back done." in (ROOT / "docs/llms.txt").read_text(encoding="utf-8")


@case
def the_heros_picture_is_the_loop_and_ends_on_your_decision():
    """Three numbered steps, and the third a decision rather than a pull request.

    The promise is *nothing ships until you say yes*: the picture shows the two
    gestures the console really offers on a ticket in review — Validate, Run
    again — and the way back to Ponos. Without script or motion it rests on
    that decision, and the ticket of the first step stays Ready all along.
    """
    page = LANDING.read_text(encoding="utf-8")
    figure = page.split('<figure class="card flow" id="flow"', 1)[1].split("</figure>", 1)[0]
    assert 'data-step="3"' in figure.split(">", 1)[0], "without script, the picture is not at the decision"
    steps = re.findall(r'<span class="flow-num">(\d)</span><b>([^<]+)</b>', figure)
    assert [n for n, _ in steps] == ["1", "2", "3"], f"the steps are not numbered one to three: {steps}"
    assert "Ponos" in steps[1][1], "the second step is not Ponos's"
    assert ">Validate<" in figure and ">Run again<" in figure, "the decision has lost one of its two buttons"
    assert "flow-link to-you" in figure and "your note" in figure, "the way back to Ponos is gone"
    assert "<ponos-robot" in figure
    statuses = re.findall(r'<span class="status[^"]*">([^<]+)</span>', figure)
    assert statuses == ["Ready"], f"the ticket of step one moves on: {statuses}"
    label = re.search(r'role="img" aria-label="([^"]+)"', figure).group(1)
    assert "Validate" in label and "Run again" in label, "the picture's description does not tell the decision"
    # The console's own words, so the picture does not promise a button that is not there.
    bits = (FRONTEND / "src/components/console/ticket-bits.tsx").read_text(encoding="utf-8")
    assert 't("Validate and publish")' in bits and 't("run again")' in bits


@case
def the_landing_page_shows_the_console_filmed_right_after_its_hero():
    """The hero promises; the section under it shows the real console doing it.

    A schematic board drawn in the page's own markup came second, and it looked
    like no screen of the product. What comes second now is the console itself,
    filmed by `scripts/film-console.mjs`: light and dark, each light enough for
    the second screen of a page, fetched only as the section comes near and
    started by the script — never by an `autoplay` the browser would honour
    before the page could ask whether motion is welcome. The four gestures stay
    under it as its legend, lit from the film's clock.
    """
    page = LANDING.read_text(encoding="utf-8")
    order = re.findall(r'<section\b[^>]*\bid="([^"]+)"', page)
    assert order[:3] == ["top", "loop", "tasks"], f"the loop no longer follows the hero: {order}"
    assert "board-demo" not in page and 'id="board"' not in page, "the schematic board is back"
    loop = page.split('<section id="loop">', 1)[1].split("</section>", 1)[0]
    video = re.search(r"<video\b[^>]*>", loop, re.S).group(0)
    for attribute in ("muted", "loop", "playsinline", 'preload="none"'):
        assert re.search(rf"\s{attribute}(?=[\s>])", video), f"the film is not {attribute}"
    assert "autoplay" not in video, "the film starts before the page can ask about motion"
    assert re.search(r'\sposter="media/console-loop-light-poster\.webp"', video), "the film has no poster"
    for theme in ("light", "dark"):
        for attribute, name in ((f"data-{theme}", f"console-loop-{theme}.mp4"),
                                (f"data-poster-{theme}", f"console-loop-{theme}-poster.webp")):
            assert f'{attribute}="media/{name}"' in video, f"the {theme} film lacks {attribute}"
            file = ROOT / "docs/media" / name
            assert file.exists(), f"docs/media/{name} is missing — node scripts/film-console.mjs"
            assert file.stat().st_size < 2_000_000, f"docs/media/{name} is too heavy for the second screen"
    for theme in ("light", "dark"):
        cues = [float(at) for at in re.search(rf'data-cues-{theme}="([^"]+)"', video).group(1).split()]
        assert len(cues) == 4 and cues[0] == 0 and cues == sorted(cues), f"one cue per gesture, in order: {cues}"
    assert loop.count('class="card step"') == 4, "the four gestures are no longer the legend"
    assert loop.index("<video") < loop.index('class="grid g4 gestures"'), "the legend comes before the film"
    script = (ROOT / "scripts/film-console.mjs").read_text(encoding="utf-8")
    assert "data-cues" in script, "the film's script no longer writes the cues into the page"
    assert "node scripts/film-console.mjs" in (ROOT / "README.md").read_text(encoding="utf-8"), (
        "the command that films the console is not documented"
    )


@case
def the_site_answers_the_icons_a_browser_asks_for_and_a_page_of_its_own_for_a_lost_one():
    """`/favicon.ico` and `/apple-touch-icon.png` are asked for whatever the page declares.

    A browser, a feed reader or an iPhone saving the page look for them at the
    root without reading a <link> — a 404 there is a blank square on a home
    screen. And an address that does not exist lands on GitHub Pages' own 404
    unless `docs/404.html` is there to say Ponos.
    """
    import struct

    ico = (ROOT / "docs/favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind) == (0, 1) and count >= 2, "favicon.ico is not an icon with its sizes"
    sizes = {ico[6 + 16 * n] or 256 for n in range(count)}
    assert {16, 32} <= sizes, f"favicon.ico lacks the tab's sizes: {sizes}"
    touch = (ROOT / "docs/apple-touch-icon.png").read_bytes()
    assert touch.startswith(b"\x89PNG") and struct.unpack(">II", touch[16:24]) == (180, 180)
    page = LANDING.read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" href="apple-touch-icon.png' in page, "the page does not declare its touch icon"
    lost = (ROOT / "docs/404.html").read_text(encoding="utf-8")
    assert "Ponos" in lost and 'href="/"' in lost, "the 404 does not lead back to the site"
    assert 'href="/mascot/favicon.svg' in lost, "a 404 at any depth loses its icon with a relative path"
    script = (ROOT / "scripts/mascot.mjs").read_text(encoding="utf-8")
    assert "favicon.ico" in script and "apple-touch-icon.png" in script, "the site's icons are not drawn from the mascot"


@case
def the_repository_s_homepage_is_the_site():
    """The package says where Ponos lives, and the example says whose repositories a session may touch."""
    import tomllib

    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert package["homepage"] == "https://the-ponos.app", package["homepage"]
    example = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert example["permissions"]["allowed"] == list(C.ALLOWED), "config.example.toml says other rules than the code"
    assert example["permissions"]["ask"] == list(C.ASK)


@case
def ponos_is_named_on_the_site_in_the_readme_and_in_the_console():
    """The robot's name, in both languages, wherever the robot is."""
    assert "Ponos" in LANDING.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Write the ticket. It comes back done." in readme.split("---", 1)[0], "the README opens elsewhere"
    assert "## Ponos, the mascot" in readme
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    mark = shell.split("export function Mark()", 1)[1].split("\n}\n", 1)[0]
    assert 'title="Ponos"' in mark and ">Ponos<" in mark, "the console's robot has no name"
    mascot = (ROOT / "docs/mascot/ponos-robot.js").read_text(encoding="utf-8")
    assert "Ponos" in mascot.split("*/", 1)[0], "the component's documentation does not say Ponos"
    assert "customElements.define('ponos-robot'" in mascot, (
        "the tag changed name — pages that embed it would lose their robot"
    )
    assert "<title>Ponos" in (ROOT / "docs/mascot/robot.svg").read_text(encoding="utf-8")


@case
def the_landing_page_tells_notion_in_one_band_with_its_badge_served_locally():
    """Notion is optional: one band, not four rows longer than the console.

    One window chains the three captures and steps that follow it; a video
    plays muted and inline or a phone opens it full screen, and nothing loads
    before the band is near. The mark is Notion's own "Made for Notion" badge,
    in both of its variants, from docs/ — their guidelines forbid the bare logo,
    and a third-party CDN would see every visit.
    """
    page = LANDING.read_text(encoding="utf-8")
    assert page.count('id="notion"') == 1, "the links to #notion land nowhere"
    band = page.split('id="notion"', 1)[1].split('class="notion-foot"', 1)[0]
    assert 'class="rows"' not in page and ".rows " not in page, "the four rows are back"
    videos = re.findall(r"<video\b[^>]*>", band)
    for name in ("notion-read-result", "notion-text", "notion-validate"):
        assert f'src="media/notion/{name}.mp4"' in band, f"{name}.mp4 is not in the band"
    assert band.index("notion-read-result.mp4") < band.index("notion-text.mp4") < band.index("notion-validate.mp4")
    assert len(videos) == 3 and band.count('class="window loop"') == 1, "the band holds more than one window"
    for video in videos:
        assert "muted" in video and "playsinline" in video, "a video would play aloud, or full screen"
        assert 'preload="none"' in video, "a video loads before the band is near"
        assert 'aria-label="' in video, "a video says nothing to a screen reader"
        assert " loop " not in video, "a video loops on itself instead of calling the next"
    steps = re.findall(r"<button\b[^>]*\bdata-step=[^>]*>", band)
    assert len(steps) == 3 and all("aria-pressed" in b for b in steps), "the steps are not buttons that say their state"
    assert "data-toggle" in band and "data-play" in band, "the window lost its pause or its play button"
    badges = re.findall(r'<img\b[^>]*alt="Made for Notion"[^>]*>', band)
    assert len(badges) == 2, "the badge needs its light and its dark variant"
    for badge in badges:
        src = re.search(r'src="([^"]+)"', badge).group(1)
        assert src.startswith("media/notion/") and (ROOT / "docs" / src).exists(), f"the badge is not served from docs/: {src}"
        assert 'height="48"' in badge, "Notion asks for a badge 48 px high on screen"
    assert "class=\"notion-foot\"" in page, "the line on Notion and the files kept in step is gone"


def _readme_anchors() -> set[str]:
    """The anchors GitHub gives the README's headings, and the ones it declares.

    GitHub's rule: lowercase, drop what is neither a letter, a digit, a space, a
    hyphen nor an underscore, and turn spaces into hyphens. Headings inside a
    code block are not headings.
    """
    anchors: set[str] = set()
    fenced = False
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = re.match(r"#{1,6} (.+)", line)
        if heading:
            text = heading.group(1).strip().lower().replace("`", "")
            anchors.add(re.sub(r"[^\w\- ]", "", text).replace(" ", "-"))
        anchors.update(re.findall(r'<a id="([^"]+)"', line))
    return anchors


@case
def the_landing_page_and_the_readme_link_to_anchors_that_exist():
    """A link into the documentation is a promise the documentation keeps.

    The site sends everything it no longer explains to a README heading, and
    the README sends its reader around itself: a heading renamed without its
    links is a reader landing at the top of a very long page.
    """
    page = LANDING.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', page))
    for anchor in re.findall(r'href="#([^"]*)"', page):
        assert anchor in ids, f"the site links #{anchor}, which it does not have"
    for target in re.findall(r'href="([^"#:]+)"', page):
        # `?v=` only makes a browser fetch the file again: the file is what has to exist.
        target = target.split("?", 1)[0]
        assert (ROOT / "docs" / target).exists(), f"the site links {target}, which docs/ does not have"
    anchors = _readme_anchors()
    linked = re.findall(r'href="https://github\.com/hermez-agency/ponos#([^"]+)"', page)
    assert linked, "the site no longer points at the documentation"
    for anchor in linked:
        assert anchor == "readme" or anchor in anchors, f"the site links README#{anchor}, which has no such heading"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for anchor in re.findall(r"\]\(#([^)]+)\)", readme):
        assert anchor in anchors, f"the README links #{anchor}, which has no such heading"


@case
def the_console_says_the_version_it_is_running_beside_the_stream_s_dot():
    """The number reaches the page, rather than staying in the payload.

    It used to be a pill in the bar, beside four others — the timer, a run in
    flight, what had been spent — and a row of states you cannot act on, drawn
    over every page, is noise with a border around it. The version, and the day
    a newer one is waiting, are said once, where the stream's own dot is: the
    end of the admin layout's bar, the one place it leaves to the application.

    Read from the React source rather than the bundle: the bundle is minified,
    and asserting on minified identifiers is asserting on the minifier.
    """
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    badge = (FRONTEND / "src/components/console/version-badge.tsx").read_text(encoding="utf-8")
    assert "Pill" not in shell, "the bar carries a row of pills again"
    assert "<VersionBadge" in shell, "the bar lost the version"
    assert "runner.version" in badge, "the console has nowhere to print the version"
    assert "runner.upgrade" in badge, "an update waiting has to be said too"
    assert "api.upgrade()" in badge, "and offered, rather than left to a terminal"


@case
def the_discussion_opens_from_a_bubble_rather_than_from_a_column():
    """One way in, in the corner every reader already looks in for a chat.

    Half the screen used to be given to a conversation whether or not there was
    one, with an entry in the menu to reach it where there was no room for the
    column and a switch in the bar to fold it away — three things to learn for
    one thing to open. It is a drawer now, over the page rather than beside it,
    and the page keeps its full width until the bubble is pressed.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    drawer = (FRONTEND / "src/components/console/talk-drawer.tsx").read_text(encoding="utf-8")
    # shadcn's own sheet, which is the drawer: nothing here draws a panel of its
    # own, and the one the sidebar already opens on a phone is this one.
    assert "SheetContent" in drawer, "the drawer is hand-rolled again"
    assert 'side="right"' in drawer, "the drawer no longer comes in from the right"
    assert "ConsolePane" in drawer, "the drawer no longer holds the console"
    # A ticket's discussion is a tab of its page: a bubble that changed role on
    # a ticket said so nowhere, and a question waiting on you sat behind it.
    assert "TicketTalk" not in drawer, "the bubble turns into a ticket's discussion again"
    page = (FRONTEND / "src/components/console/ticket-page.tsx").read_text(encoding="utf-8")
    assert "<TicketTalk " in page, "a ticket's page no longer holds its discussion"
    app = (FRONTEND / "src/App.tsx").read_text(encoding="utf-8")
    assert "TalkDrawer" in app, "nothing opens the discussion"
    assert "ConsolePane" not in app, "the console has a column of its own again"
    assert "asideLabel" not in app, "the bar carries the switch that folds it away again"
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "ConsolePane" not in scope, "the menu has an entry for the drawer again"


@case
def the_console_is_drawn_in_react_resource_view_s_admin_layout():
    """One admin interface, the package's, rather than two kept side by side.

    The console had a frame of its own — a sidebar, a bar, a router over the
    History API — around pages that were already react-resource-view's. The
    frame is the package's now: a scope declares the resources and the menu,
    `createAdminLayout` draws them, and TanStack Router holds the history
    through the adapter the package ships for it. What the console drew by hand
    is gone rather than kept beside it.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "createAdminLayout" in scope, "the console draws its own frame again"
    for resource in ("tickets", "projects", "schedules", "settings"):
        assert f"entry({resource.upper()}" in scope, f"the menu has no entry for {resource}"
    app = (FRONTEND / "src/App.tsx").read_text(encoding="utf-8")
    assert "ScopeProvider" in app, "the pages are no longer drawn in the scope's layout"
    assert "RouterProvider" in app, "TanStack Router no longer holds the history"
    views = (FRONTEND / "src/lib/resource-view.ts").read_text(encoding="utf-8")
    assert "tanstackAdapter" in views, "the views reach the router some other way again"
    for gone in ("app-sidebar.tsx", "header.tsx", "resource-pane.tsx"):
        assert not (FRONTEND / "src/components/console" / gone).exists(), (
            f"{gone} is back, beside the layout that replaced it"
        )
    assert not (FRONTEND / "src/components/ui/sidebar.tsx").exists(), "a second sidebar is back"
    # The component that rereads the board on every event sits over every view
    # of the tickets — react-resource-view 1.0 merges a view's `components`
    # into the resource's — and no view takes it away: without it the board
    # stops following the stream.
    tickets = (FRONTEND / "src/resources/tickets.tsx").read_text(encoding="utf-8")
    assert "components: { top: BoardTop }" in tickets, (
        "the board no longer rereads itself when the stream moves it"
    )
    assert "top: null" not in tickets, "a view of the tickets no longer follows the stream"


@case
def a_project_is_a_resource_with_two_layouts_and_a_form():
    """Clickable, editable, and drawn two ways — which is what the screen is for.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol. A
    project drawn by hand again — a pane with rows in it — would take the page
    back to a list you can only look at.
    """
    declared = (FRONTEND / "src/resources/projects.tsx").read_text(encoding="utf-8")
    assert "createViewResource" in declared, "the projects are a hand-rolled pane again"
    assert "layout.cards(" in declared, "the card layout is gone"
    assert "layout.table(" in declared, "the second layout is gone"
    permissions = declared.split("permissions:")[1].split("\n")[0]
    assert "update" not in permissions and "readonly" not in permissions, "a project is read-only again"
    assert "api.saveProject" in declared, "nothing writes the project back"
    page = (FRONTEND / "src/components/console/project-page.tsx").read_text(encoding="utf-8")
    assert "ResourceViewButton" in page, "the page offers no way into the form"
    assert (FRONTEND / "src/lib/router.tsx").read_text(encoding="utf-8").count(
        "?view=console/projects/list"
    ), "the address the pane had stopped leading to the projects"


@case
def a_schedule_is_a_resource_drawn_in_the_package_s_own_layouts():
    """The one page whose rows are dates, laid out as dates.

    It was a pane: cards drawn by hand, a form written by hand, and a date
    formatted into "in 6 days" by hand. All three exist in the package the board
    and the projects are already drawn with, so the schedules are a resource
    like them — a table to compare them in and a calendar to read the next
    occurrence off, and no second design language on the one screen that had
    one.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    declared = (FRONTEND / "src/resources/schedules.tsx").read_text(encoding="utf-8")
    assert "createViewResource" in declared, "the schedules are a hand-rolled pane again"
    assert "layout.table(" in declared, "the table layout is gone"
    assert "layout.calendar<" in declared, "the calendar layout is gone"
    assert 'dateField: "when"' in declared, "the calendar no longer lays out the launches by when they land"
    assert "api.saveSchedule" in declared, "nothing writes a schedule back"
    assert "api.createSchedule" in declared, "nothing writes a new schedule"
    # The columns a pass writes back are how the runner knows an occurrence has
    # been taken; a form that offered them would let you make one happen twice,
    # or never. The list shows them; the fields the forms are built from do not.
    fields = declared.split("const fields")[1].split("const createForm")[0]
    for written_back in ("next", "last"):
        assert f"{written_back}: {{" not in fields, (
            f"the form offers `{written_back}`, which a pass writes back"
        )
    for gone in ("schedules-pane.tsx", "schedule-form.tsx"):
        assert not (FRONTEND / "src/components/console" / gone).exists(), (
            f"{gone} is back, beside the resource that replaced it"
        )
    assert "?view=console/schedules/list" in (FRONTEND / "src/lib/router.tsx").read_text(
        encoding="utf-8"
    ), "the address the pane had stopped leading to the schedules"


@case
def a_session_is_followed_on_its_ticket_rather_than_on_a_page_of_sessions():
    """The live page listed sessions by the id of their log, and nothing more.

    `24f9704c` said nothing of the ticket it was: the session is read where the
    ticket is — a section of its page, a line on its card — and the page is gone.
    Its address still leads somewhere: a link somebody kept lands on the board.
    """
    assert not (FRONTEND / "src/resources/live.tsx").exists(), "the live page is back"
    assert not (FRONTEND / "src/components/console/live-pane.tsx").exists(), "the live pane is back"
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "LIVE" not in scope, "the menu has an entry for the live page again"
    router = (FRONTEND / "src/lib/router.tsx").read_text(encoding="utf-8")
    assert 'live: "/?view=console/tickets/list"' in router, "/?page=live no longer reaches the board"
    page = (FRONTEND / "src/components/console/ticket-page.tsx").read_text(encoding="utf-8")
    assert "<TicketLive" in page, "a ticket's page no longer shows its session"
    assert '(running ? "live"' in page, "a running ticket no longer opens on its session"
    tickets = (FRONTEND / "src/resources/tickets.tsx").read_text(encoding="utf-8")
    assert "<CardLive" in tickets, "a running card no longer says what it is doing"
    assert "<RunnerStrip" in tickets, "the runner's figures are nowhere on the board"
    log = (FRONTEND / "src/components/console/session-log.tsx").read_text(encoding="utf-8")
    assert "<details" in log, "a tool call is no longer folded"
    assert "/worktrees/" in log, "the worktree's path is written out in full again"
    assert "outline(steps" in log, "the session is drawn step by step again, not in its broad lines"


@case
def the_console_menu_is_a_name_and_a_count():
    """Seven entries of two lines each is a page to read, not a menu to use.

    Every entry used to carry a sentence under its name — how many tickets were
    ready, whether the timer was on — which is what the pages themselves say,
    said again in the smaller type. What is worth knowing at a glance is a
    count, and a count fits beside a name.
    """
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    assert "badge?" in shell, "an entry can no longer carry a count"
    assert "detail" not in shell, "an entry carries a sentence again"
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "component: MenuEntry" in scope, "the menu is drawn without its counts again"


@case
def a_project_that_cannot_be_read_says_what_the_server_answered():
    """The one screen where a generic sentence cost an afternoon.

    The page a project opens on was handed `error: true` and nothing else, so
    "This project could not be read." was the whole of what a browser showed
    while the server was answering `no such route: /api/projects/<id>`. What
    the server said belongs on the page — shown, not swallowed and not replaced
    by a blank. react-resource-view 1.0 hands it over as `loadError`.
    """
    declared = (FRONTEND / "src/resources/projects.tsx").read_text(encoding="utf-8")
    getter = declared.split("getItem:")[1].split("\n")[0]
    assert "catch" not in getter, "a failed read is swallowed before the page hears of it"
    page = (FRONTEND / "src/components/console/project-page.tsx").read_text(encoding="utf-8")
    assert "why(context.loadError)" in page, "the page shows the failure without its reason again"
    assert "This project could not be read." in page, "the failure is not said at all"


@case
def the_console_route_of_one_project_is_the_one_the_page_asks_for():
    """The address the browser builds has to be an address the server answers.

    They are written in two languages and checked by nobody at build time: the
    page asks `/api/projects/<id>`, and the server matches that route with a
    regular expression. A 404 there reads, in the browser, as a project that
    could not be read.
    """
    routes = (ROOT / "src/ponos/web/server.py").read_text(encoding="utf-8")
    pattern = re.search(r'r"(/api/projects/[^"]+)"', routes)
    assert pattern, "the server no longer routes one project"
    asked = "/api/projects/" + "3eaf7e7b99c04adeae76ac6ecd52cdd0"
    assert re.fullmatch(pattern.group(1), asked), f"{asked} is not a route this server answers"
    assert "`/api/projects/${id}`" in (FRONTEND / "src/lib/api.ts").read_text(encoding="utf-8"), (
        "the console asks for a project somewhere else now"
    )


@case
def a_turn_is_drawn_as_markdown_on_a_shadcn_bubble():
    """Both sides write markdown, so neither side is shown its source.

    A session answers in headings, lists and fenced code, on a ticket and in
    the workspace's transcript alike; a bubble that printed that as it arrived
    would be asking a reader to parse the asterisks themselves. The surface it
    is said on is shadcn's `Bubble` rather than a `div` this repository styles,
    so the palette stays the components'.
    """
    turn = (FRONTEND / "src/components/console/turn.tsx").read_text(encoding="utf-8")
    assert "<Markdown" in turn, "the transcript shows the markdown instead of drawing it"
    assert "BubbleContent" in turn, "the bubble is hand-rolled again"
    assert (FRONTEND / "src/components/ui/bubble.tsx").is_file(), "shadcn's bubble is gone"


@case
def the_console_scrolls_in_its_own_colours():
    """The bars the console scrolls on are drawn by the console, not the browser.

    Left alone, a browser paints them for a light page — pale and wide over a
    panel that is neither — and the console scrolls almost everywhere. Both
    spellings have to stay: the pseudo-elements for Chrome and WebKit, the two
    standard properties for Firefox, which has nothing else.
    """
    for style in ((FRONTEND / "src/index.css"), _built("css")):
        text = style.read_text(encoding="utf-8")
        assert "color-scheme" in text, "the browser is left to guess at the page's colours"
        assert "::-webkit-scrollbar-thumb" in text, "Chrome and WebKit keep the browser's bar"
        assert "scrollbar-color" in text, "Firefox keeps the browser's bar"
        assert "@supports not selector(::-webkit-scrollbar)" in text, (
            "Chrome prefers the standard properties, and would drop the rounded thumb"
        )


@case
def the_console_buttons_show_the_hand():
    """Whatever can be clicked shows a hand, whatever is disabled says no.

    Tailwind 4's preflight stopped putting `cursor: pointer` on `<button>`, so
    every button without its own class kept the arrow and nothing said it could
    be clicked. The rule lives once, in the base layer, for the source and the
    built bundle both.
    """
    for style in ((FRONTEND / "src/index.css"), _built("css")):
        text = re.sub(r"\s+", "", style.read_text(encoding="utf-8"))
        assert "button:not(:disabled)" in text and "cursor:pointer" in text, (
            "the buttons keep the arrow"
        )
        assert "cursor:not-allowed" in text and "button:disabled" in text, (
            "a disabled button looks as clickable as the others"
        )


@case
def the_console_asks_for_nothing_it_did_not_ship():
    """Nothing the page loads comes from anywhere but this machine.

    The console is served by `http.server` on loopback, and a page that reached
    for a library on a CDN would be a console that looks broken on a train and
    tells somebody else when you opened it. React and shadcn/ui change nothing
    here: they are compiled into the bundle beside the page, not fetched.
    """
    # An `xmlns` is a name, not an address; what is looked for here is the
    # shapes that actually make the browser open a socket.
    reaches = ('src="http', "src='http", 'href="http', "href='http",
               "url(http", "url('http", 'url("http', "@import", "//unpkg", "//cdn")
    for path in _shipped():
        text = path.read_text(encoding="utf-8", errors="replace")
        for shape in reaches:
            assert shape not in text, f"{path.name} reaches off the machine: {shape}"


@case
def the_console_says_the_configuration_in_french_too():
    """Every sentence this module writes about a setting has a French entry.

    The settings page is the one place where what the console shows comes from
    Python: a label, the line of help under it, the section it sits in. They
    reach the browser in the words written here and are looked up in
    `frontend/src/lib/french.ts` by those very words — so a sentence reworded
    on this side and not on that one would quietly go back to English on a
    console somebody set to French.

    All but one: the head of a sub-type's column in the model table, «
    Feature », is the sub-type's own word, and a sub-type is never translated
    (see `SUBTYPES` in subtypes.py) — so it must have no entry at all.
    """
    dictionary = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    said = [words for group in web_settings.GROUPS for words in (group.title, group.blurb)]
    said += [words for fold in web_settings.FOLDS.values() for words in fold]
    for section in web_settings.SECTIONS:
        said += [section.title, section.blurb]
        for field in section.fields:
            said += [field.label, field.help, field.after, field.unit, field.placeholder]
            said += [label for _, label in field.options]
            if field.grid == "subtype":
                assert f'"{field.short}":' not in dictionary, f"“{field.short}” is translated"
            else:
                said.append(field.short)
    for sentence in said:
        # As a key, not anywhere in the file: "Check the board every" is
        # in "Check the board every (seconds)", which translates nothing of it.
        keyed = f'"{sentence}":' in dictionary or re.search(
            rf"^\s*{re.escape(sentence)}:", dictionary, re.MULTILINE
        )
        assert not sentence or keyed, f"nothing translates “{sentence}” — add it to french.ts"


@case
def the_console_offers_the_two_languages_it_has():
    """The settings carry the switch, and the browser is asked before you are.

    It sat at the right edge of the bar, on every page, which is a lot of room
    for a thing somebody changes once. A language is a setting: it is drawn on
    the settings page, in the section that is about this console — even though
    it is the browser's own and never reaches `config.toml`.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    i18n = (FRONTEND / "src/lib/i18n.ts").read_text(encoding="utf-8")
    assert '"en"' in i18n and '"fr"' in i18n, "the console no longer offers both"
    assert "navigator.languages" in i18n, "the browser's own languages are not read"
    assert "resolvedOptions().timeZone" in i18n, "the time zone no longer answers for it"
    settings = (FRONTEND / "src/components/console/settings-page.tsx").read_text(encoding="utf-8")
    assert "LanguagePicker" in settings, "the settings have nowhere to change the language"


@case
def the_version_is_rewritten_where_the_product_reads_it():
    """`__version__` is what --version and the console header print.

    The rewrite is a regular expression over the real file, so this checks it
    against the real file's shape rather than against a fixture that agrees
    with it by construction.
    """
    with tempfile.TemporaryDirectory() as directory:
        init = Path(directory) / "__init__.py"
        init.write_text(release.INIT.read_text(encoding="utf-8"), encoding="utf-8")
        release.write_version("9.9.9", init)
        assert release.read_version(init) == "9.9.9"
        assert '__version__ = "9.9.9"' in init.read_text(encoding="utf-8")


# -- a board made of files ----------------------------------------------------


@contextmanager
def _board(**settings_overrides):
    """A throwaway Markdown board, and the naming settings it is read under."""
    directory = tempfile.mkdtemp()
    try:
        yield files.Board(Path(directory) / "board", _settings(**settings_overrides))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@case
def a_frontmatter_survives_the_round_trip():
    """What `render` writes, `parse` has to read back — every shape of it.

    The file is the board: a value that comes back as something else is a
    status nobody can filter on, or a day of the month that is no longer one.
    """
    front = {
        "id": "a" * 32,
        "title": "Corriger l'entête « à faire »",
        "created": "2026-09-14T09:00:00+00:00",
        "Status": "In review",
        "Active": False,
        "Cost": 1.25,
        "Day": "1",
        "Project": ["p1", "p2"],
        "Empty": "",
    }
    back, body = files.parse(files.render(front, "# Titre\n\nUn corps."))
    assert back == front, back
    assert body == "# Titre\n\nUn corps."
    # Twice through, byte for byte: a pass that rewrote the same file would
    # otherwise look like a change to the sync, for ever.
    once = files.render(front, "x")
    assert files.render(*files.parse(once)) == once


@case
def a_file_with_no_frontmatter_is_all_body():
    front, body = files.parse("Je suis Camille Martin.\n")
    assert front == {} and body == "Je suis Camille Martin."


@case
def tickets_are_written_and_read_back_as_markdown():
    with _board() as board:
        page_id = board.create_row(
            "tickets", "Corriger l'entête", {"Status": "Ready", "Priority": "High"}
        )
        board.append_markdown(page_id, "## À faire\n\nRelire la page.")
        page = board.page(page_id)
        assert page.title == "Corriger l'entête"
        assert store.read(page, "Status") == "Ready"
        assert store.read(page, "Priority") == "High"
        assert "Relire la page." in board.blocks_text(page_id)
        # The file is where somebody would look for it, named after the ticket.
        written = list((board.root / "tickets").glob("*.md"))
        assert len(written) == 1 and written[0].name.startswith("corriger-l-entete-")

        board.update("tickets", page_id, {"Status": "In progress", "Runner": "ponos@here"})
        assert store.read(board.page(page_id), "Status") == "In progress"
        assert store.read(board.page(page_id), "Runner") == "ponos@here"
        # And the body is untouched by a property write.
        assert "Relire la page." in board.blocks_text(page_id)


@case
def a_markdown_ticket_reads_its_brief_without_its_live_reports():
    """A file has no toggle: the story of a run is fenced, and the brief leaves it out."""
    with _board() as board:
        page_id = board.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})
        board.append_markdown(page_id, "## À faire\n\nRelire la page.")
        _run_on(board, "fr", "Je lis la configuration.", ok=False, page_id=page_id)
        board.append_markdown(page_id, "---\nPull request ouverte : x/y#3")
        _run_on(board, "en", "Reading the header again.", page_id=page_id)
        brief = board.blocks_text(page_id, live=False)
        assert brief == "## À faire\n\nRelire la page.\n\n---\nPull request ouverte : x/y#3", brief
        whole = board.blocks_text(page_id)
        assert "Je lis la configuration." in whole and "Reading the header again." in whole
        # One stretch per run, opened by its toggle and holding all its steps.
        assert whole.count(files.LIVE_OPEN) == 2 == whole.count(files.LIVE_CLOSE), whole
        assert whole.index("Je lis la configuration.") < whole.index(files.LIVE_CLOSE)


@case
def a_markdown_board_answers_the_filters_the_runner_builds():
    with _board() as board:
        ready = board.create_row("tickets", "À faire", {"Status": "Ready"})
        board.create_row("tickets", "Finie", {"Status": "Done"})
        found = board.query("tickets", {"property": "Status", "select": {"equals": "Ready"}})
        assert [page.id for page in found] == [ready]
        # The woken filter: everything but the statuses that speak for a ticket.
        awake = board.query(
            "tickets",
            {"and": [
                {"property": "Status", "select": {"does_not_equal": "Ready"}},
                {"property": "Status", "select": {"does_not_equal": "Done"}},
            ]},
        )
        assert awake == []
        # A filter this cannot read must not silently empty the board.
        assert len(board.query("tickets", {"timestamp": "created_time"})) == 2


@case
def projects_the_context_and_the_schedules_live_in_files_too():
    """The three things the ticket's UI has to be able to show without Notion."""
    with _board() as board:
        project = board.create_row("projects", "ponos", {"Repository": "user/repo"})
        assert store.read(board.page(project), "Repository") == "user/repo"

        board.set_context("Je suis Camille Martin, développeur web.")
        assert board.context() == "Je suis Camille Martin, développeur web."
        assert board.blocks_text(files.CONTEXT_PAGE) == board.context()

        schedule = board.create_row(
            "schedules",
            "Revue des dépendances",
            {"Cadence": "Weekly", "At": "09:00", "Day": "Monday", "Active": True},
        )
        row = schedules.read(board.page(schedule), board.settings())
        assert row.cadence == "Weekly" and row.at == "09:00" and row.day == "Monday"
        assert row.active is True and not row.problem
        # And a schedule turned off from the console comes back off.
        board.update("schedules", schedule, {"Active": False})
        assert schedules.read(board.page(schedule), board.settings()).active is False


@case
def a_markdown_board_keeps_a_discussion_per_page():
    with _board() as board:
        page_id = board.create_row("tickets", "Une question", {})
        board.comment(page_id, "La question ?")
        board.comment(page_id, "Et la suite,\n\navec un blanc au milieu.", discussion_id="d-1")
        said = board.comments(page_id)
        assert [comment.text for comment in said] == [
            "La question ?",
            "Et la suite,\n\navec un blanc au milieu.",
        ]
        assert said[1].discussion_id == "d-1"
        assert all(comment.created_by == board.me() for comment in said)


@case
def the_whole_runner_runs_against_files_with_no_notion_at_all():
    """A full pass in `storage.mode = "markdown"`, network unplugged.

    The one test that answers the question the mode exists for: does the runner
    — the queue, the claim, the session, the report — work when there is no
    integration, no token and no workspace to resolve? Notion's own client is
    replaced by something that raises if it is so much as constructed, so a
    single call that reached for it would fail here rather than in production.
    """
    with _state_home(), _board() as board:
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text(
            f'[storage]\nmode = "markdown"\npath = "{board.root}"\n'
            "[runner]\ndry_run = false\nprogress = false\nreply = false\n"
            "auto_update = false\nnotify = false\nattach_sessions = false\n",
            encoding="utf-8",
        )
        configuration = C.load(path)
        # Nothing here may be reached for. A configuration with no token would
        # only have produced a 401; this produces a traceback naming the caller.
        def refuse(*_args, **_kwargs):
            raise AssertionError("markdown mode must never construct a Notion client")

        # Typed by hand: a ticket with no type would first be classified, and
        # that is a question of its own — see the cases on kinds.py.
        page_id = board.create_row(
            "tickets", "Écrire l'annonce", {"Status": "Ready", "Type": "Writing"}
        )
        board.append_markdown(page_id, "Rédige une annonce courte.")
        board.set_context("Je suis Camille Martin.")

        real_client = notion.Client
        notion.Client = refuse
        try:
            configuration.require_usable()  # no token, and that is not a fault
            run = Runner(configuration, quiet=True)
            assert isinstance(run.client, files.Board)
            assert run.database == "tickets"
            assert run.workspace.context == "Je suis Camille Martin."
            ready = run.ready()
            assert [ticket.title for ticket in ready] == ["Écrire l'annonce"]

            with _no_session(answer="C'est écrit.", writes={"ANSWER.md": "# Annonce\n\nVoilà."}):
                results = run.tick()
        finally:
            notion.Client = real_client

        assert [result["status"] for result in results] == ["done"], results
        done = board.page(page_id)
        assert store.read(done, "Status") == "Done"
        assert "Voilà." in board.blocks_text(page_id), board.blocks_text(page_id)
        # The report went into the ticket's discussion, as it does on Notion.
        assert any(voice.is_report(comment.text) for comment in board.comments(page_id))


# -- the two boards, kept in step --------------------------------------------


class _NotionBoard:
    """Notion reduced to a dictionary, with the surface the mirror uses.

    Not a mock: it keeps pages, bodies and `last_edited_time`, because the whole
    of the reconciliation is about which side moved and when. What it does not
    have is a network, which is the point.
    """

    def __init__(self, context: str = "") -> None:
        self.pages: dict[str, store.Page] = {}
        self.bodies: dict[str, str] = {}
        self.where: dict[str, str] = {}   # page id -> database
        self.context = context
        self.said: list[tuple[str, str]] = []
        self._counter = 0

    # -- the shape -----------------------------------------------------------

    def resolve_database(self, identifier):
        return identifier

    def forget_database(self, database_id):
        pass

    def schema(self, database_id):
        return files.schemas(_settings())[database_id]

    def options(self, database_id, name):
        return []

    def title_property(self, database_id):
        return "Name"

    def workspace(self, settings):
        space = workspace.Workspace(
            tickets="tickets", projects="projects", agents="agents", schedules="schedules",
            rows={"Context": "ctx"}, context_page="ctx",
        )
        space.context = self.context
        return space

    # -- reading -------------------------------------------------------------

    def query(self, database_id, filter_=None):
        return [
            page for page_id, page in self.pages.items()
            if self.where[page_id] == database_id
        ]

    def page(self, page_id):
        if page_id not in self.pages:
            raise store.StoreError(f"no such page: {page_id}")
        return self.pages[page_id]

    def blocks_text(self, block_id, depth=0, *, live=True):
        if block_id == "ctx":
            return self.context
        return self.bodies.get(block_id, "")

    def comments(self, page_id):
        return []

    def me(self):
        return "notion-user"

    def my_name(self):
        return "Ponos"

    # -- writing -------------------------------------------------------------

    def _touch(self, page_id, at=""):
        page = self.pages[page_id]
        page.raw["last_edited_time"] = at or _stamp()


    def create_row(self, database_id, title, values=None, at=""):
        self._counter += 1
        page_id = f"{self._counter:032x}"
        self.pages[page_id] = store.Page(
            id=page_id, url=f"https://notion.so/{page_id}", title=title,
            properties={"Name": store.written("title", title)},
            raw={"created_time": at or _stamp(), "last_edited_time": at or _stamp()},
        )
        self.where[page_id] = database_id
        self.update(database_id, page_id, values or {}, at=at)
        return page_id

    def update(self, database_id, page_id, values, at=""):
        page = self.pages[page_id]
        schema = self.schema(database_id)
        for name, value in values.items():
            if name == "Name":
                page.title = str(value)
            shape = store.written(schema.get(name, "rich_text"), value)
            if shape is not None:
                page.properties[name] = shape
        self._touch(page_id, at)

    def append_markdown(self, page_id, markdown, at=""):
        if page_id == "ctx":
            self.context = f"{self.context}\n\n{markdown}".strip()
            return 1
        self.bodies[page_id] = f"{self.bodies.get(page_id, '')}\n\n{markdown}".strip()
        self._touch(page_id, at)
        return 1

    def replace_markdown(self, page_id, markdown, at=""):
        if page_id == "ctx":
            self.context = markdown.strip()
            return 1
        self.bodies[page_id] = markdown.strip()
        self._touch(page_id, at)
        return 1

    def comment(self, page_id, text, discussion_id=""):
        self.said.append((page_id, text))

    def append_blocks(self, block_id, blocks):
        return []

    def update_block(self, block_id, payload):
        pass


def _stamp() -> str:
    """The fake Notion's clock: the real one, to the microsecond.

    To the microsecond because that is the resolution the reconciliation reads
    both sides at — two writes in the same second would otherwise be one write
    as far as it could tell, and a conflict test would pass by accident.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@contextmanager
def _mirror(context: str = ""):
    """Both boards and a fresh set of stamps, with nothing shared between runs."""
    directory = Path(tempfile.mkdtemp())
    try:
        here = _NotionBoard(context)
        there = files.Board(directory / "board", _settings())
        both = sync.Mirror(here, there)
        yield here, there, both, sync.Stamps(directory / "ponos.db")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@case
def a_ticket_written_in_notion_appears_in_the_files():
    with _mirror("Je suis Camille Martin.") as (here, there, both, marks):
        page_id = here.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})
        here.replace_markdown(page_id, "Relire la page d'accueil.")

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == [
            "created-in-markdown", "notion→markdown"
        ], [entry.what for entry in report.carried]
        mirrored = there.page(page_id)
        assert mirrored.title == "Corriger l'entête"
        assert store.read(mirrored, "Status") == "Ready"
        assert there.blocks_text(page_id) == "Relire la page d'accueil."
        assert there.context() == "Je suis Camille Martin."

        # A second pass on an unchanged board carries nothing: without that,
        # every fifteen minutes would rewrite every file on the disk.
        assert not both.synchronise(_settings(), stamps=marks).carried

        # And a change in Notion afterwards reaches the file.
        here.update("tickets", page_id, {"Status": "Done"})
        again = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in again.carried] == ["notion→markdown"]
        assert store.read(there.page(page_id), "Status") == "Done"


@case
def a_ticket_written_in_a_file_appears_in_notion():
    with _mirror() as (here, there, both, marks):
        local = there.create_row("tickets", "Écrire l'annonce", {"Status": "Ready"})
        there.replace_markdown(local, "Une annonce courte.")

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == ["created-in-notion"]
        created = report.carried[0].page
        assert here.pages[created].title == "Écrire l'annonce"
        assert store.read(here.pages[created], "Status") == "Ready"
        assert here.bodies[created] == "Une annonce courte."
        # The file now wears Notion's identifier: the URL, the relations and
        # every report from here on carry that one, and nothing carries its own.
        assert there.page(created).title == "Écrire l'annonce"

        # Changed in the file afterwards, and carried the other way.
        there.update("tickets", created, {"Status": "In review"})
        there.replace_markdown(created, "Une annonce, relue.")
        again = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in again.carried] == ["markdown→notion"]
        assert store.read(here.pages[created], "Status") == "In review"
        assert here.bodies[created] == "Une annonce, relue."


@case
def a_page_moved_on_both_sides_is_a_conflict_the_newest_wins():
    """The rule `storage.conflict` names, and the line it leaves behind.

    Losing an edit is not the failure mode to avoid here — one of the two is
    going to lose whatever the rule says. The failure mode is losing it
    *quietly*, so the conflict is journalled with both timestamps and the name
    of the side that won.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)

        # Both move, and Notion moves last.
        there.update("tickets", page_id, {"Status": "Blocked"})
        here.update("tickets", page_id, {"Status": "Done"})

        report = both.synchronise(_settings(), stamps=marks)
        assert len(report.conflicts) == 1
        said = report.conflicts[0].detail
        assert "Notion wins" in said and "newest" in said
        assert store.read(there.page(page_id), "Status") == "Done"

        # And the other way round: the file is the later one.
        here.update("tickets", page_id, {"Status": "Failed"})
        there.update("tickets", page_id, {"Status": "In review"})
        back = both.synchronise(_settings(), stamps=marks)
        assert len(back.conflicts) == 1
        assert "Markdown wins" in back.conflicts[0].detail
        assert store.read(here.pages[page_id], "Status") == "In review"


@case
def a_deletion_is_written_down_and_never_carried_across():
    """Nothing the sync does may remove a page. It says so instead.

    A file disappears for a hundred reasons — a bad merge, a stray `rm`, an
    editor writing to the wrong place — and none of them is a decision to delete
    a ticket. The same holds the other way: a Notion page somebody archived is
    not a reason to throw away the file they may have been editing.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)
        _, path = there._find(page_id)
        path.unlink()

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.deletions] == ["deleted-in-markdown"]
        assert page_id in here.pages, "the Notion page must be left exactly as it was"
        assert not report.carried, "a gone file is not a page to create again"

        # And it stays said: the next pass repeats it rather than re-creating.
        assert both.synchronise(_settings(), stamps=marks).deletions

        # The other way: the Notion page goes, the file stays.
        local = there.create_row("tickets", "L'autre", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)
        created = [page for page in here.pages if here.pages[page].title == "L'autre"][0]
        del here.pages[created]
        gone = both.synchronise(_settings(), stamps=marks)
        assert "deleted-in-notion" in [entry.what for entry in gone.deletions]
        assert there.page(created).title == "L'autre"
        del local


@case
def the_journal_keeps_what_the_reconciliations_did():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ponos.db"
        report = sync.Report()
        report.note("conflict", "tickets", "abc", "Le ticket", "both moved")
        report.note("deleted-in-notion", "tickets", "def", "L'autre", "gone")
        sync.write_journal(report, path)
        sync.write_journal(report, path)
        entries = sync.journal(3, path)
        assert len(entries) == 3, "the journal appends rather than replaces"
        assert entries[-1]["what"] == "deleted-in-notion"
        assert entries[-1]["title"] == "L'autre"
        assert entries[-1]["at"]


@case
def the_standing_context_travels_both_ways():
    with _mirror("Écrit dans Notion.") as (here, there, both, marks):
        both.synchronise(_settings(), stamps=marks)
        assert there.context() == "Écrit dans Notion."

        there.set_context("Réécrit dans le fichier.")
        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == ["markdown→notion"]
        assert here.context == "Réécrit dans le fichier."

        here.context = "Réécrit dans Notion."
        back = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in back.carried] == ["notion→markdown"]
        assert there.context() == "Réécrit dans Notion."


@case
def a_mirrored_write_lands_on_both_boards_at_once():
    """Between two reconciliations, the run's own work must be on both sides.

    A ticket claimed at 14:02 and reconciled at 14:15 would otherwise spend
    thirteen minutes reading "Ready" in the files while a session works on it.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)

        both.update("tickets", page_id, {"Status": "In progress"})
        assert store.read(there.page(page_id), "Status") == "In progress"
        both.append_markdown(page_id, "Un rapport.")
        assert "Un rapport." in there.blocks_text(page_id)
        both.comment(page_id, "Fini.")
        assert [comment.text for comment in there.comments(page_id)] == ["Fini."]
        # And what the mirror reads is still Notion's answer.
        assert both.page(page_id).title == "Le ticket"


# -- the configuration that chooses a board -----------------------------------


@case
def the_storage_mode_decides_which_store_is_opened():
    configuration = _config("")
    assert configuration.storage.mode == "notion"
    assert isinstance(store.open(configuration), notion.Client)

    with tempfile.TemporaryDirectory() as directory:
        markdown_only = _config(f'[storage]\nmode = "markdown"\npath = "{directory}/board"\n')
        assert markdown_only.storage.path == Path(directory) / "board"
        assert isinstance(store.open(markdown_only), files.Board)
        both = _config(f'[storage]\nmode = "both"\npath = "{directory}/board"\n')
        assert isinstance(store.open(both), sync.Mirror)

    # A word nobody meant must not quietly decide where the board lives.
    assert _config('[storage]\nmode = "postgres"\n').storage.mode == "notion"
    assert _config('[storage]\nconflict = "mine"\n').storage.conflict == "newest"


@case
def a_markdown_installation_needs_neither_token_nor_workspace():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[storage]\nmode = "markdown"\n', encoding="utf-8")
    C.load(path).require_usable()  # must not raise

    # And a Notion one still says exactly what it is missing.
    empty = Path(tempfile.mkdtemp()) / "config.toml"
    empty.write_text("[notion]\n", encoding="utf-8")
    try:
        C.load(empty).require_usable()
    except C.ConfigError as error:
        assert "notion.token" in str(error)
        assert "markdown" in str(error), "the way out is worth naming here"
    else:
        raise AssertionError("a Notion installation with no token must not be usable")


# -- the three screens that must work without Notion --------------------------


def _markdown_api(board: files.Board) -> web_api.Api:
    """An Api reading a board made of files, and nothing else built.

    The same shape `_bare_api` builds, with the store swapped and a
    `[storage]` that says so: these three panes exist to be usable on an
    installation where there is no integration to ask anything of.
    """
    api = _bare_api(board, me=board.me())
    api._config = C.Config(
        notion=C.Notion(),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(),
        storage=C.Storage(mode="markdown", path=board.root),
    )
    api._runner.config = api._config
    api._runner._workspace = board.workspace(api._config.notion)
    # Where a project's clone is looked for, for the page that says it.
    api._runner.resolver = projects.Resolver(api._config.runner.workspace_root, {})
    # What `state()` folds in and nothing here exercises: the chat and the
    # command line are the console's own, and have no board behind them.
    api.chat = type("Chat", (), {"state": lambda self: {}})()
    api.commands = type("Commands", (), {"allowed": (), "busy": False})()
    return api


@case
def the_console_lists_every_project_it_knows_of():
    """The board's own, and the ones only the configuration names.

    A name the file maps to a path and the board has never heard of is still a
    project of this installation — and the row says so, rather than sending
    somebody looking for a page that does not exist.
    """
    with _board() as board:
        code = board.create_row("projects", "ponos", {"Repository": "user/repo"})
        board.create_row("projects", "Site vitrine", {})
        ticket = board.create_row("tickets", "Un ticket", {"Status": "Ready"})
        board.update("tickets", ticket, {"Project": [code]})

        api = _markdown_api(board)
        api._config.projects["Jeu d'usine"] = "/home/salva/workspace/usine"
        asked: list[str] = []
        query = api.runner.client.query
        api.runner.client.query = lambda database, *rest, **named: (
            asked.append(database) or query(database, *rest, **named)
        )
        drawn = api.all_projects()
        assert api.runner.database not in asked, "the tickets are the console's to count"

    rows = {project["name"]: project for project in drawn["projects"]}
    assert set(rows) == {"ponos", "Site vitrine", "Jeu d'usine"}
    assert rows["ponos"]["kind"] == "code"
    assert rows["ponos"]["repository"] == "user/repo"
    # Counted by the console on the tickets it already holds: a count here was
    # the whole tickets database read again on every call.
    assert "tickets" not in rows["ponos"]
    # No repository declared anywhere: a document project, not a broken one.
    assert rows["Site vitrine"]["kind"] == "document"
    assert rows["Jeu d'usine"]["source"] == "config"
    assert rows["Jeu d'usine"]["path"] == "/home/salva/workspace/usine"
    assert drawn["storage"] == "markdown"


@case
def the_console_opens_a_project_and_writes_it_back():
    """A project is a page you can change, and the brief is why it is worth opening.

    What is written goes to the column the page already carries — a project
    database is written by hand, so "Repository" is sometimes "github" — and a
    save that invented a second column beside the one somebody filled in would
    be a save that changes nothing anybody can see.
    """
    with _board() as board:
        page = board.create_row("projects", "ponos", {"github": "user/repo"})
        board.replace_markdown(page, "Écris en français.")

        api = _markdown_api(board)
        opened = api.project(page)
        assert opened["name"] == "ponos"
        assert opened["repository"] == "user/repo"
        assert opened["content"] == "Écris en français."
        # No clone under the workspace root: the page says nowhere, not a guess.
        assert opened["located"] == ""

        written = api.save_project(
            page,
            {
                "name": "ponos",
                "repository": "user/autre-repo",
                "path": "~/workspace/ponos",
                "content": "Écris en français, et jamais de pyproject.",
            },
        )
        assert written["repository"] == "user/autre-repo"
        assert written["path"] == "~/workspace/ponos"
        assert written["content"] == "Écris en français, et jamais de pyproject."
        # The column somebody filled in, not a second one beside it.
        assert store.read(board.page(page), "github") == "user/autre-repo"
        assert "Repository" not in board.page(page).properties

        # Replacing, not appending: the brief is a value, like the context.
        api.save_project(page, {"content": "Écris en français, et jamais de pyproject."})
        assert board.blocks_text(page) == "Écris en français, et jamais de pyproject."

        # A payload with nothing in it says so rather than quietly doing nothing.
        try:
            api.save_project(page, {})
        except ValueError:
            pass
        else:
            raise AssertionError("a change with nothing to change must say so")

        # What the window asked for at the creation is corrected here too: the
        # description and the site in their columns, the type by its repository.
        written = api.save_project(page, {"description": "  Le  runner. ", "site": "https://ponos.dev"})
        assert written["description"] == "Le runner."
        assert written["site"] == "https://ponos.dev"
        assert store.read(board.page(page), "URL") == "https://ponos.dev"
        for refused in ({"site": "ponos.dev"}, {"kind": "code", "repository": "", "path": ""}):
            try:
                api.save_project(page, refused)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{refused} must be refused")
        written = api.save_project(page, {"kind": "document", "repository": "user/autre-repo"})
        assert written["kind"] == "document"
        assert written["repository"] == "" and written["path"] == ""
        written = api.save_project(page, {"kind": "code", "repository": "user/repo"})
        assert written["kind"] == "code"

        # And a project the console has never heard of is a 404, not an empty page.
        try:
            api.project("f" * 32)
        except LookupError:
            pass
        else:
            raise AssertionError("an unknown project must not read as a blank one")


def _creatable(board: files.Board, language: str = "fr") -> web_api.Api:
    """A markdown Api that creates projects, speaking `language`."""
    api = _markdown_api(board)
    api._config.runner = C.Runner(language=language)
    api._runner.config = api._config
    api.creation = web_creation.Creation(api)
    api.watch = type("Watch", (), {"nudge": lambda self: None})()
    return api


def _refused(create, field: str) -> str:
    """The sentence a creation is refused with, which must be about `field`."""
    try:
        create()
    except web_creation.Refused as error:
        assert error.field == field, (error.field, str(error))
        return str(error)
    raise AssertionError(f"expected a refusal about {field}")


@case
def a_github_repository_is_written_as_its_whole_address():
    for given in (
        "hermez-agency/ponos",
        "https://github.com/hermez-agency/ponos",
        "https://github.com/hermez-agency/ponos.git",
        "github.com/hermez-agency/ponos/",
        "git@github.com:hermez-agency/ponos.git",
        "https://github.com/hermez-agency/ponos/tree/main/src",
    ):
        assert web_creation.github_url(given) == "https://github.com/hermez-agency/ponos", given
    for given in ("ponos", "https://gitlab.com/someone/ponos", "a/b/c", "-bad/ponos", "owner/..", "owner/a b"):
        assert web_creation.github_url(given) == "", given


@case
def a_project_is_created_from_the_console_with_what_its_page_says():
    """A writing project, then a code one from GitHub: the page carries the
    columns the database already has, the brief is its body, and the answer is
    a row of the list — the one the list then holds."""
    with _board() as board:
        board.create_row("projects", "Existant", {"github": "someone/else"})
        api = _creatable(board)

        made = api.creation.create(
            {
                "name": "  Site   vitrine ",
                "description": "La page d'accueil.",
                "kind": "document",
                # Left over from the form before the type was changed.
                "repository": "owner/ignored",
                "site": "https://example.com",
                "content": "# Voix\n\nÉcris court.",
            }
        )
        assert made["name"] == "Site vitrine" and made["kind"] == "document"
        assert made["repository"] == "" and made["source"] == "board"
        page = board.page(made["id"])
        assert page.title == "Site vitrine"
        assert store.read(page, "Description") == "La page d'accueil."
        assert store.read(page, "URL") == "https://example.com"
        assert not store.read(page, "github")
        assert board.blocks_text(made["id"]) == "# Voix\n\nÉcris court."

        code = api.creation.create({"name": "Ponos", "kind": "code", "repository": "hermez-agency/ponos"})
        assert code["kind"] == "code"
        assert code["repository"] == "https://github.com/hermez-agency/ponos"
        # The column this database calls its repository, not a second one.
        assert store.read(board.page(code["id"]), "github") == code["repository"]
        assert "Repository" not in board.page(code["id"]).properties

        listed = {row["name"]: row for row in api.all_projects()["projects"]}
        assert listed["Ponos"]["id"] == code["id"] and listed["Ponos"]["kind"] == "code"
        assert listed["Site vitrine"]["kind"] == "document"

        # A ticket created on it right after is tied to it, and its runner finds
        # the clone of the repository it declares by its remote.
        root = Path(tempfile.mkdtemp())
        try:
            clone = root / "ponos"
            subprocess.run(["git", "init", "-q", str(clone)], check=True)
            subprocess.run(
                ["git", "-C", str(clone), "remote", "add", "origin", "git@github.com:hermez-agency/ponos.git"],
                check=True,
            )
            ticket = api.create_ticket("Un ticket", project=code["id"])["id"]
            relation = store.read(board.page(ticket), board.settings().prop("project"))
            assert relation == [code["id"]]
            found = projects.Resolver(root, {}).resolve(board, relation[0])
            assert found.path == clone and found.github == code["repository"]
        finally:
            shutil.rmtree(root, ignore_errors=True)


@case
def a_project_is_created_from_a_folder_and_names_its_remote():
    with _board() as board, tempfile.TemporaryDirectory() as directory:
        clone = Path(directory) / "jeu"
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(
            ["git", "-C", str(clone), "remote", "add", "origin", "git@github.com:SalvadorCardona/jeu.git"],
            check=True,
        )
        api = _creatable(board)

        checked = api.creation.check(path=str(clone))
        assert checked["path"] == str(clone)
        assert checked["origin"] == "https://github.com/SalvadorCardona/jeu"

        made = api.creation.create({"name": "Jeu", "kind": "code", "path": f"{clone}/"})
        assert made["path"] == str(clone)
        assert made["repository"] == "https://github.com/SalvadorCardona/jeu"
        assert store.read(board.page(made["id"]), "Path") == str(clone)
        found = projects.Resolver(Path(directory), {}).resolve(board, made["id"])
        assert found.path == clone and found.is_code


@case
def a_project_the_console_cannot_create_is_refused_before_anything_is_written():
    """A name taken, a repository that is not GitHub's, a folder that is not
    there — each said under its field, in the runner's language, and the board
    left as it was."""
    with _board() as board, tempfile.TemporaryDirectory() as directory:
        board.create_row("projects", "Ponos", {})
        api = _creatable(board)
        create = api.creation.create

        said = _refused(lambda: create({"name": "PONOS", "kind": "document"}), "name")
        assert said == "Un projet s'appelle déjà « Ponos »."
        _refused(lambda: create({"name": "   ", "kind": "document"}), "name")
        said = _refused(lambda: create({"name": "Neuf", "kind": "code", "repository": "gitlab.com/a/b"}), "repository")
        assert "gitlab.com/a/b" in said and "GitHub" in said
        _refused(lambda: create({"name": "Neuf", "kind": "code"}), "repository")
        missing = f"{directory}/nowhere"
        said = _refused(lambda: create({"name": "Neuf", "kind": "code", "path": missing}), "path")
        assert said == f"Il n'y a pas de dossier à {missing} sur cette machine."
        _refused(lambda: create({"name": "Neuf", "kind": "code", "path": directory}), "path")
        _refused(lambda: create({"name": "Neuf", "kind": "code", "path": "relative/folder"}), "path")
        _refused(lambda: create({"name": "Neuf", "kind": "document", "site": "example.com"}), "site")
        assert [page.title for page in board.query("projects")] == ["Ponos"]

        # In English for a runner that speaks it.
        said = _refused(lambda: _creatable(board, "en").creation.create({"name": "ponos"}), "name")
        assert said == "A project is already called “Ponos”."

        # What the form is told as it is filled in: a refusal said, not raised.
        checked = api.creation.check("not a repository", missing)
        assert "repository_error" in checked and "path_error" in checked
        checked = api.creation.check("owner/name")
        assert checked == {"repository": "https://github.com/owner/name", "cloned": ""}


@case
def the_console_server_creates_a_project_and_says_which_field_it_refuses():
    """The route, end to end: a project created is a row of the list; a refusal
    is a 400 whose violation names the field, which is what the form draws."""
    import urllib.error
    import urllib.parse
    import urllib.request

    from ponos.web import server as web_server

    with _board() as board:
        api = _creatable(board)
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"
        headers = {"Authorization": "Bearer tok", "Content-Type": "application/json", "X-Ponos": "1"}

        def ask(path: str, body: dict | None = None) -> tuple[int, dict]:
            data = None if body is None else json.dumps(body).encode()
            request = urllib.request.Request(base + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read() or b"{}")

        try:
            status, made = ask("/api/projects", {"name": "Neuf", "kind": "document"})
            assert status == 200 and made["name"] == "Neuf" and made["kind"] == "document", made
            status, refused = ask("/api/projects", {"name": "neuf", "kind": "document"})
            assert status == 400
            assert refused["violations"] == [{"propertyPath": "name", "message": refused["error"]}]
            status, checked = ask("/api/projects/check?" + urllib.parse.urlencode({"repository": "o/n"}))
            assert status == 200 and checked["repository"] == "https://github.com/o/n", checked
        finally:
            console.shutdown()
            console.server_close()


def _deletable(board: files.Board):
    """A markdown Api with a project of three tickets, and one elsewhere."""
    settings = board.settings()
    code = board.create_row("projects", "ponos", {"Repository": "user/repo"})
    elsewhere = board.create_row("projects", "Site vitrine", {})
    tickets = {}
    for title, status, project in (
        ("Prêt", settings.state("ready"), code),
        ("En cours", settings.state("running"), code),
        ("Fini", settings.state("done"), code),
        ("Ailleurs", settings.state("ready"), elsewhere),
    ):
        ticket = board.create_row("tickets", title, {settings.prop("status"): status})
        board.update("tickets", ticket, {settings.prop("project"): [project]})
        tickets[title] = ticket
    api = _markdown_api(board)
    api._config.notion = settings
    api._runner.config = api._config
    api._reader = web_board.Reader(journal=lambda report: None)
    api.removal = web_removal.Removal(api)
    api.watch = type("Watch", (), {"nudge": lambda self: None})()
    return api, code, tickets


@case
def deleting_a_project_needs_its_name_and_changes_nothing_without_it():
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        for confirm in ("", "Ponos", "ponosx"):
            try:
                api.removal.delete(code, {"confirm": confirm})
            except ValueError as error:
                assert "ponos" in str(error)
            else:
                raise AssertionError(f"“{confirm}” must not delete a project")
        assert board.page(code).title == "ponos", "refused, so still on the board"
        status = board.settings().prop("status")
        assert store.read(board.page(tickets["Prêt"]), status) == board.settings().state("ready")
        try:
            api.removal.delete("f" * 32, {"confirm": "ponos"})
        except LookupError:
            pass
        else:
            raise AssertionError("an unknown project must be a 404")


@case
def a_deleted_project_leaves_the_console_and_its_tickets_are_stopped_not_lost():
    """Gone from the list at once; tickets the runner could take are blocked and
    say why; the others, and the other project's, are left alone; nothing is
    removed for good — and what was spent on it stays in the history."""
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        settings = board.settings()
        status = settings.prop("status")
        ideas.record(code, "haiku", 0.5, [{"kind": "ticket", "title": "Une idée"}])
        state.record({"id": tickets["Fini"], "status": "done", "project": "ponos", "cost_usd": 2.0})

        done = api.removal.delete(code, {"confirm": "ponos"})

        assert (done["tickets"], done["blocked"], done["trashed"]) == (3, 2, 0)
        assert [one["name"] for one in api.all_projects()["projects"]] == ["Site vitrine"]
        for title, expected in (
            ("Prêt", settings.state("blocked")),
            ("En cours", settings.state("blocked")),
            ("Fini", settings.state("done")),
            ("Ailleurs", settings.state("ready")),
        ):
            assert store.read(board.page(tickets[title]), status) == expected, title
        assert "supprimé" in board.comments(tickets["Prêt"])[-1].text or "deleted" in board.comments(
            tickets["Prêt"]
        )[-1].text
        assert not board.comments(tickets["Ailleurs"])
        # The page is put aside, not deleted: it is still on the disk.
        assert list((board.root / "trash" / "projects").glob("ponos-*.md"))
        assert done["ideas"] == 1 and not ideas.listed(code)
        assert sum(float(one.get("cost_usd") or 0) for one in state.history(100)) == 2.0

        # The ticket is still reachable, and the runner refuses its project.
        try:
            projects.Resolver(Path(tempfile.mkdtemp()), {}).resolve(board, code)
        except (LookupError, store.StoreError):
            pass
        else:
            raise AssertionError("a deleted project must not resolve")


@case
def deleting_a_project_may_trash_its_tickets_too():
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        done = api.removal.delete(code, {"confirm": "ponos", "trash_tickets": True})
        assert (done["trashed"], done["blocked"]) == (3, 0)
        titles = {page.title for page in board.query("tickets")}
        assert titles == {"Ailleurs"}
        assert len(list((board.root / "trash" / "tickets").glob("*.md"))) == 3
        assert api.reader.get(tickets["Prêt"]) is None, "dropped from what the console holds"


@case
def a_project_with_a_session_running_is_not_deleted():
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        running = web_live.active
        web_live.active = lambda *a, **k: [{"source": ticket_module.short_id(tickets["En cours"]), "log": "x"}]
        try:
            api.removal.delete(code, {"confirm": "ponos"})
        except RuntimeError as error:
            assert "En cours" in str(error)
        else:
            raise AssertionError("a running session must stop the deletion")
        finally:
            web_live.active = running
        assert board.page(code).title == "ponos"
        status = board.settings().prop("status")
        assert store.read(board.page(tickets["Prêt"]), status) == board.settings().state("ready")


@case
def a_project_in_the_notion_trash_does_not_resolve():
    """The trash keeps a page readable by its ID; that is what must not be worked on."""

    class Backend:
        def page(self, page_id):
            return store.Page(id=page_id, url="", title="Site", raw={"archived": True})

    try:
        projects.Resolver(Path(tempfile.mkdtemp()), {}).resolve(Backend(), "p" * 32)
    except LookupError as error:
        assert "deleted" in str(error) and "Site" in str(error)
    else:
        raise AssertionError("an archived project must not resolve")


@case
def a_brief_is_saved_only_from_the_version_it_was_opened_at():
    """Edited in the console, the brief is never written over a newer one.

    The editor opens at a `version` and saves against it: a brief somebody
    wrote to meanwhile — in Notion, from another tab — is a conflict to read
    again, not a text to overwrite. And what is saved is what the runner reads
    at the next ticket, with nothing kept from the one it replaced.
    """
    with _board() as board:
        page = board.create_row("projects", "ponos", {"github": "user/repo"})
        board.replace_markdown(page, "# Voix\n\n- Écris en français.")
        api = _markdown_api(board)

        opened = api.project_brief(page)
        assert opened["content"] == "# Voix\n\n- Écris en français."
        assert opened["losses"] == {}, "a board of files loses nothing to Markdown"
        assert opened["version"] == api.project(page)["version"]

        # The text goes there and back unchanged, whatever the editor spells it.
        written = api.save_project(page, {"content": "# Voix\n\n* Écris en français.\n", "base": opened["version"]})
        assert board.blocks_text(page) == "# Voix\n\n* Écris en français."
        assert written["version"] != opened["version"]
        assert projects.Resolver(Path("/nowhere"), {}).brief(board, page) == "# Voix\n\n* Écris en français."

        # Somebody else wrote while the editor was open: refused, and kept.
        board.replace_markdown(page, "Écrit ailleurs.")
        try:
            api.save_project(page, {"content": "Mon texte.", "base": opened["version"]})
        except RuntimeError:
            pass
        else:
            raise AssertionError("a brief that changed since it was opened was overwritten")
        assert board.blocks_text(page) == "Écrit ailleurs."

        # Read again, it saves.
        again = api.project_brief(page)
        api.save_project(page, {"content": "Mon texte.", "base": again["version"]})
        assert board.blocks_text(page) == "Mon texte."


@case
def a_brief_that_markdown_cannot_hold_is_not_rewritten_unannounced():
    """Notion holds more than a line of text does; the console says what that costs.

    `markdown.lost` names, block by block, what `plain` would flatten and
    `to_blocks` would not give back — and a save that knows about it refuses
    until the caller says it has been told.
    """
    from ponos import markdown

    def text(content, **notes):
        part = {"type": "text", "plain_text": content, "href": notes.pop("href", None), "annotations": notes}
        return {"rich_text": [part]}

    assert markdown.lost({"type": "paragraph", "paragraph": text("Rien à perdre.")}) == []
    assert markdown.lost({"type": "heading_2", "heading_2": text("Titre", color="default", bold=False)}) == []
    assert markdown.lost({"type": "paragraph", "paragraph": text("gras", bold=True)}) == ["formatting"]
    assert markdown.lost({"type": "paragraph", "paragraph": text("lien", href="https://x.y")}) == ["link"]
    assert markdown.lost({"type": "paragraph", "paragraph": {"rich_text": [{"type": "mention", "plain_text": "@Salva"}]}}) == ["mention"]
    assert markdown.lost({"type": "toggle", "toggle": text("Plié")}) == ["toggle"]
    assert markdown.lost({"type": "child_database", "child_database": {"title": "Notes"}}) == ["child_database"]
    # A row is lost with its table, which is said once.
    assert markdown.lost({"type": "table_row"}) == []

    blocks = {
        "page": [
            {"id": "a", "type": "paragraph", "paragraph": text("Net.")},
            {"id": "b", "type": "toggle", "toggle": text("Plié"), "has_children": True},
            {"id": "c", "type": "child_database", "child_database": {"title": "Notes"}},
        ],
        "b": [
            {"id": "d", "type": "paragraph", "paragraph": text("gras", bold=True)},
            {"id": "e", "type": "callout", "callout": text("Attention"), "has_children": True},
        ],
        "e": [{"id": "f", "type": "toggle", "toggle": text("Encore"), "has_children": True}],
        "f": [{"id": "g", "type": "bookmark", "bookmark": {"url": "https://x.y"}, "has_children": True}],
        "g": [{"id": "h", "type": "image", "image": {}}],
    }
    client = notion.Client("ntn_x")
    client._request = lambda method, path, body=None: {  # type: ignore[method-assign]
        "results": blocks.get(path.split("/")[2], []), "has_more": False
    }
    found = client.losses("page")
    assert found == {"toggle": 2, "child_database": 1, "formatting": 1, "callout": 1, "bookmark": 1, "nested": 1}, found

    with _board() as board:
        page = board.create_row("projects", "ponos", {})
        board.replace_markdown(page, "Texte.")
        api = _markdown_api(board)
        # The board of files has nothing to lose; make it say otherwise.
        board.losses = lambda *_: {"toggle": 1}  # type: ignore[method-assign]
        base = api.project_brief(page)["version"]
        try:
            api.save_project(page, {"content": "Autre.", "base": base})
        except ValueError:
            pass
        else:
            raise AssertionError("a page was rewritten without being told what it would lose")
        assert board.blocks_text(page) == "Texte."
        api.save_project(page, {"content": "Autre.", "base": base, "accept_losses": True})
        assert board.blocks_text(page) == "Autre."


@case
def the_console_reads_and_rewrites_the_standing_context():
    """Rewrites, never appends: the context is a value, not a history.

    Saving it twice has to leave one text. Everything else this console writes
    appends — a comment under a question, a report under a ticket — so this is
    the one place the distinction has to be made on purpose.
    """
    with _board() as board:
        board.set_context("Première version.")
        api = _markdown_api(board)
        assert api.context()["text"] == "Première version."
        assert api.context()["editable"]

        api.save_context("Deuxième version.")
        assert board.context() == "Deuxième version."
        api = _markdown_api(board)
        api.save_context("Deuxième version.")
        assert board.context() == "Deuxième version.", "a second save must not stack"

        # A workspace with nowhere to write says so rather than offering a save
        # that could only fail.
        blind = _markdown_api(board)
        blind._runner._workspace.context_page = ""
        assert not blind.context()["editable"]
        try:
            blind.save_context("x")
        except ValueError as error:
            assert "Context" in str(error)
        else:
            raise AssertionError("a context with no page must not pretend to save")


@case
def a_ticket_created_from_the_console_carries_its_priority_type_and_model():
    """A score and two selects in the form, written as the board takes them.

    They used to be set in Notion afterwards, by hand. Offered only for the
    columns the board has — a value for a missing one would be dropped on the
    way in — and a type left empty stays empty, for the runner to classify.
    The priority is a score from 0 to 100, 50 when none is said, refused
    outside that range.
    """
    with _board() as board:
        api = _markdown_api(board)
        api._schema_at = time.time()
        api._reader = web_board.Reader(journal=lambda report: None)
        api._outbox = web_board.Outbox(journal=lambda report: None)
        api.watch = _Nudged()
        read = api.board()
        choices = read["choices"]
        assert read["priority"] is True and "priority" not in choices
        assert [option["value"] for option in choices["model"]] == ["opus", "sonnet", "haiku"]
        assert {option["value"]: option["label"] for option in choices["type"]}["writing"] == "Writing"

        made = api.create_ticket("Écrire l'annonce", ready=False, priority=80, kind="writing", model="haiku")
        page = board.page(made["id"])
        settings = api.config.notion
        assert store.read(page, settings.prop("priority")) == 80
        assert store.read(page, settings.prop("type")) == "Writing"
        assert store.read(page, settings.prop("model")) == "haiku"
        assert not store.read(page, settings.prop("status")), "not ready is a draft"

        bare = board.page(api.create_ticket("Sans rien")["id"])
        assert not store.read(bare, settings.prop("type")), "an empty type is the runner's to deduce"
        assert store.read(bare, settings.prop("priority")) == 50, "none said is the middle"
        for wrong in (101, -1, "vite"):
            try:
                api.create_ticket("Hors bornes", priority=wrong)
            except ValueError:
                pass
            else:
                raise AssertionError(f"a priority of {wrong!r} must be refused")
        try:
            api.create_ticket("Mauvais type", kind="poem")
        except ValueError:
            pass
        else:
            raise AssertionError("a type that is none of the four must be refused")

    # A board without those columns is offered none of them.
    api = _bare_api(_ColumnsClient(["Ready"]))
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    assert api.board()["choices"] == {}


# -- ideas -------------------------------------------------------------------


def _ideas_api(board: files.Board) -> web_api.Api:
    """A console on a Markdown board, ready to find and keep ideas."""
    api = _markdown_api(board)
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    api._outbox = web_board.Outbox(journal=lambda report: None)
    api.watch = _Nudged()
    api.ideas = web_ideas.Ideas(api)
    # Never a session of the real `claude` behind a test's back: a test that
    # wants an idea scored runs what was put aside itself.
    api.ideas.later = lambda work: None
    return api


def _proposing(answers: list[list[dict]], cost: float = 0.02):
    """A `session.run` that answers each batch in turn, and keeps what it was asked."""
    asked: list[dict] = []

    def fake_run(text, **rest):
        asked.append({"prompt": text, **rest})
        return session.Outcome(
            ok=True, blocked=False, session_id="s-ideas", summary="",
            log=Path("/dev/null"), cost_usd=cost,
            answer="Voici :\n```json\n" + json.dumps(answers[len(asked) - 1], ensure_ascii=False) + "\n```",
        )

    return fake_run, asked


def _idea(title: str, kind: str = "ticket", **more) -> dict:
    return {
        "title": title,
        "description": more.pop("description", f"Parce que {title.lower()}."),
        "kind": kind,
        "where": more.pop("where", "frontend/src"),
        "done": more.pop("done", ["Les tests passent"]),
        "out": more.pop("out", ["Le reste"]),
    }


@case
def an_idea_answer_is_read_whatever_wraps_it():
    """A fence, a sentence, a kind a project cannot have, a description too long."""
    answer = 'Sure!\n```json\n[{"title": "  Mode   sombre ", "kind": "project",' \
        ' "description": "un\\ndeux\\ntrois\\nquatre", "done": "ça marche"},' \
        ' {"title": ""}, "rien"]\n```\nVoilà.'
    found = ideas.parse(answer, "project")
    assert [idea["title"] for idea in found] == ["Mode sombre"]
    assert found[0]["kind"] == "ticket", "a project's ideas are tickets, always"
    assert found[0]["description"] == "un\ndeux\ntrois", "three lines at most"
    assert found[0]["detail"]["done"] == ["ça marche"]
    assert ideas.parse(answer, "global")[0]["kind"] == "project"
    assert ideas.parse("no JSON here", "global") == []

    assert ideas.similar("Ajouter un mode sombre", "ajouter un mode sombre !")
    assert ideas.similar("Add a dark mode", "Add dark mode")
    assert not ideas.similar("Add a dark mode", "Add an export to CSV")
    assert not ideas.similar("Export to CSV", "Export to PDF"), "ideas share their openings"
    assert ideas.similar("Mode sombre de la console", "La console en mode sombre")
    kept, dropped = ideas.fresh(
        [_idea("Exporter en CSV"), _idea("Exporter en CSV."), _idea("Créer un mode sombre")],
        ["Créer un mode sombre"],
    )
    assert [idea["title"] for idea in kept] == ["Exporter en CSV"]
    assert len(dropped) == 2


@case
def an_idea_is_sorted_into_one_category_or_left_unsorted():
    """UX/UI, feature, security or technical — one of the four, or "" rather than a guess."""
    assert '"category"' in ideas.prompt(project="Usine"), "the model is asked to choose"
    answer = json.dumps(
        [
            {"title": "Un thème sombre", "category": " UX "},
            {"title": "Échapper le HTML", "category": "security"},
            {"title": "Deux catégories", "category": ["feature", "technical"]},
            {"title": "Une catégorie inventée", "category": "marketing"},
        ]
    )
    assert [idea["category"] for idea in ideas.parse(answer, "project")] == [
        "ux", "security", "", ""
    ]
    with _state_home():
        _, stored = ideas.record("p", "haiku", None, ideas.parse(answer, "project"))
        assert [idea.shown()["category"] for idea in stored] == ["ux", "security", "", ""]
        written = ideas.written("p", "Un cache", category="technical")
        assert written.category == "technical"
        assert ideas.written("p", "Autre", category="tout").category == ""
        assert ideas.edit(written.id, "Un cache, enfin", "").category == "technical", (
            "rewording it keeps its category"
        )
        assert ideas.edit(written.id, "Un cache", "", category="feature").category == "feature"
        assert ideas.edit(written.id, "Un cache", "", category="").category == ""


@case
def an_idea_comes_with_a_score_bounded_by_the_grid_or_none_at_all():
    """Out of 100, by the grid written in the prompt; bounded, and "not scored" for anything else."""
    asked = ideas.prompt(project="Usine")
    for line in ('"score"', '"score_reason"', "up to 40", "up to 25", "up to 20", "up to 15"):
        assert line in asked, line
    answer = json.dumps(
        [
            {"title": "Noté", "score": 85, "score_reason": "  Beaucoup   d'impact. "},
            {"title": "Trop haut", "score": 150},
            {"title": "Trop bas", "score": -5},
            {"title": "En texte", "score": "72"},
            {"title": "Arrondi", "score": 69.6},
            {"title": "Pas un nombre", "score": "high"},
            {"title": "Un booléen", "score": True},
            {"title": "Une liste", "score": [80]},
            {"title": "Sans score"},
        ]
    )
    found = ideas.parse(answer, "project")
    assert [idea["score"] for idea in found] == [85, 100, 0, 72, 70, None, None, None, None]
    assert found[0]["detail"]["score_reason"] == "Beaucoup d'impact."
    assert found[-1]["detail"]["score_reason"] == ""
    with _state_home():
        _, stored = ideas.record("p", "haiku", None, found)
        shown = [idea.shown() for idea in stored]
        assert [one["score"] for one in shown] == [85, 100, 0, 72, 70, None, None, None, None]
        assert shown[0]["score_reason"] == "Beaucoup d'impact." and shown[0]["tone"] == "green"
        assert shown[-1]["tone"] == "" and shown[-1]["scoring"] is False, "not scored, and not being"
        assert [idea.title for idea in ideas.unscored("p")] == [
            "Pas un nombre", "Un booléen", "Une liste", "Sans score"
        ]
        ideas.decide(stored[-1].id, "discarded")
        assert len(ideas.unscored("p")) == 3, "a thrown idea is not worth paying a score for"

    scores = ideas.parse_scores(
        'Voilà : [{"id": 3, "score": 120, "score_reason": "Oui."}, {"id": "4", "score": "x"},'
        ' {"id": 9, "score": 50}, {"id": 5, "score": 41}]',
        [3, 4, 5],
    )
    assert scores == {3: (100, "Oui."), 5: (41, "")}, "only those asked for, and only numbers"


@case
def a_score_is_green_orange_or_red_by_the_same_two_thresholds_on_both_sides():
    """39 is red, 40 and 69 orange, 70 green — and the console reads the same numbers."""
    assert [ideas.tone(score) for score in (0, 39, 40, 69, 70, 100)] == [
        "red", "red", "orange", "orange", "green", "green"
    ]
    assert ideas.tone(None) == ""
    search = (FRONTEND / "src/lib/idea-search.ts").read_text(encoding="utf-8")
    assert f"export const GREEN = {ideas.GREEN}\n" in search, "the page and the server disagree on green"
    assert f"export const ORANGE = {ideas.ORANGE}\n" in search, "the page and the server disagree on orange"


@case
def the_ideas_from_before_scores_are_not_scored():
    """The migration adds a score to every idea, NULL — not a zero."""
    with _state_home():
        location = db.path()
        before = db.MIGRATIONS.index(db._ideas_have_a_score)
        raw = db.open_at(location, db.MIGRATIONS[:before])
        raw.execute(
            "INSERT INTO ideas (scope, project, kind, title, status, created_at)"
            " VALUES ('project', 'p', 'ticket', 'Ancienne', 'proposed', '2026-10-01')"
        )
        raw.close()
        db.close()
        old = ideas.every("p")[0]
        assert old.score is None and old.shown()["tone"] == ""
        assert ideas.scored(old.id, 55, "Moyen.").shown()["score"] == 55
        with db.transaction(immediate=False) as connection:
            assert connection.execute("SELECT score FROM ideas").fetchone() == (55,)


@case
def an_idea_written_by_hand_is_scored_behind_the_answer_that_saved_it():
    """Saved, it says "…"; the light model scores it by the grid; a failed answer leaves it not scored."""
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        board.replace_markdown(project, "Un jeu d'usine en navigateur.")
        api = _ideas_api(board)
        api.ideas._person = ("Salva", "")
        put_aside: list = []
        api.ideas.later = put_aside.append
        ideas.written(project, "Un mode sombre")
        written = api.ideas.create({"project": project, "title": "Une carte des usines", "description": "Pour voir."})
        assert written["score"] is None and written["scoring"] is True, "the pill says …"
        assert len(put_aside) == 1, "scored behind the answer, not before it"

        asked: list[dict] = []

        def fake_run(text, **rest):
            asked.append({"prompt": text, **rest})
            return session.Outcome(
                ok=True, blocked=False, session_id="s-score", summary="", log=Path("/dev/null"),
                cost_usd=0.001,
                answer=json.dumps([{"id": written["id"], "score": 82, "score_reason": "Utile et petit."}]),
            )

        original, session.run = session.run, fake_run
        try:
            put_aside.pop()()
        finally:
            session.run = original
        assert len(asked) == 1 and asked[0]["model"] == "haiku", "the light model, classify_model's"
        assert asked[0]["max_budget_usd"] == ideas.SCORE_CEILING_USD
        call = asked[0]["prompt"]
        assert "up to 40" in call and f"{written['id']}. Une carte des usines\nPour voir." in call
        assert "Un jeu d'usine en navigateur." in call, "scored against the brief"
        assert "- Un mode sombre" in call, "and against the other ideas"
        scored = ideas.get(written["id"]).shown()
        assert (scored["score"], scored["tone"], scored["scoring"]) == (82, "green", False)
        assert scored["score_reason"] == "Utile et petit."

        mcp_one = api.ideas.write(project, "ticket", "Un tutoriel")
        assert mcp_one["scoring"] is True, "an idea an MCP client wrote is scored the same way"
        original, session.run = session.run, lambda text, **rest: session.Outcome(
            ok=True, blocked=False, session_id="s", summary="", log=Path("/dev/null"), answer="Je ne sais pas."
        )
        try:
            put_aside.pop()()
        finally:
            session.run = original
        failed = ideas.get(mcp_one["id"]).shown()
        assert failed["score"] is None and failed["scoring"] is False, "not scored, and said so"


@case
def a_scoring_that_fails_says_why_on_the_idea_instead_of_staying_silent():
    """Over budget, unreadable, or too big to start: the cause stays on the idea, and the pass tells the page."""
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        put_aside: list = []
        api.ideas.later = put_aside.append
        published: list = []
        original_publish = api.hub.publish
        api.hub.publish = lambda topic, **rest: published.append((topic, rest))
        first = ideas.written(project, "Une carte des usines")
        second = ideas.written(project, "Un tutoriel")
        assert ideas.SCORE_CEILING_USD >= 0.5, "a call costs 0.12 to 0.14 dollars: 0.10 stopped every one"

        def outcome(**rest):
            return session.Outcome(
                ok=False, blocked=True, session_id="s", summary="", log=Path("/dev/null"), **rest
            )

        original, session.run = session.run, lambda text, **rest: outcome(over_budget=True, cost_usd=0.1356)
        try:
            api.ideas.score_unscored(project)
            put_aside.pop()()
        finally:
            session.run = original
        shown = ideas.get(first.id).shown()
        assert shown["score"] is None and shown["scoring"] is False
        assert "may spend" in shown["score_error"], shown["score_error"]
        assert ("ideas", {"project": project, "failed": shown["score_error"]}) in published

        original, session.run = session.run, lambda text, **rest: outcome(error="credit balance too low")
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        assert ideas.get(second.id).shown()["score_error"] == "credit balance too low"

        original, session.run = session.run, lambda text, **rest: session.Outcome(
            ok=True, blocked=False, session_id="s", summary="", log=Path("/dev/null"), answer="Je ne sais pas."
        )
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        assert "could not be read" in ideas.get(second.id).shown()["score_error"]

        def crash(text, **rest):
            raise OSError("no claude")

        original, session.run = session.run, crash
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        assert "no claude" in ideas.get(second.id).shown()["score_error"], "an exception is kept, not swallowed"

        original, session.run = session.run, lambda text, **rest: session.Outcome(
            ok=True, blocked=False, session_id="s", summary="", log=Path("/dev/null"),
            answer=json.dumps([{"id": second.id, "score": 60, "score_reason": "Bien."}]),
        )
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        done = ideas.get(second.id).shown()
        assert (done["score"], done["score_error"]) == (60, ""), "a score clears the error"
        api.hub.publish = original_publish


@case
def a_scoring_prompt_of_the_real_size_fits_under_the_ceiling_and_a_huge_one_is_not_started():
    """The estimate is checked before the session starts: a call that would be stopped is not paid for."""
    big = [
        ideas.Idea(id=n, batch=None, scope="global", project="", kind="ticket",
                   title=f"Idée {n} " + "x" * 80, description="d" * 600)
        for n in range(ideas.SCORE_BATCH)
    ]
    prompt = ideas.score_prompt(
        big, brief="b" * 10000, context="c" * 10000,
        tickets=[("t" * 90, "ready")] * 100, known=["k" * 90] * 400,
    )
    assert ideas.score_estimate(prompt) < ideas.SCORE_CEILING_USD, "even at its limits, a prompt is under the ceiling"
    assert ideas.score_estimate("x" * 400000) > ideas.SCORE_CEILING_USD


@case
def the_ideas_with_no_score_are_scored_in_batches_under_a_ceiling_said_first():
    """A ceiling before it starts, twenty to a call, a scope per call — and one pass at a time."""
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        for number in range(25):
            ideas.written(project, f"Idée du projet {number}")
        ideas.written("", "Idée de l'espace")
        told = api.ideas.unscored(None)
        assert (told["count"], told["calls"]) == (26, 3), "two calls for the project, one for the workspace"
        assert told["ceiling_usd"] == round(3 * ideas.SCORE_CEILING_USD, 2) and told["model"] == "haiku"
        assert api.ideas.unscored("")["count"] == 1

        put_aside: list = []
        api.ideas.later = put_aside.append
        started = api.ideas.score_unscored(None)
        assert started["running"] is True and started["count"] == 26
        try:
            api.ideas.score_unscored(None)
        except RuntimeError:
            pass
        else:
            raise AssertionError("a second pass waits for the first")

        sizes: list[int] = []

        def fake_run(text, **rest):
            numbers = [int(found) for found in re.findall(r"^(\d+)\. ", text, re.M)]
            sizes.append(len(numbers))
            return session.Outcome(
                ok=True, blocked=False, session_id="s", summary="", log=Path("/dev/null"),
                answer=json.dumps([{"id": number, "score": 30 + number, "score_reason": "."} for number in numbers]),
            )

        original, session.run = session.run, fake_run
        try:
            put_aside.pop()()
        finally:
            session.run = original
        assert sorted(sizes) == [1, 5, 20], sizes
        assert api.ideas.unscored(None) == {
            "count": 0, "calls": 0, "ceiling_usd": 0, "model": "haiku", "running": False
        }
        assert all(idea.score is not None for idea in ideas.every(None))


@case
def ideas_for_a_project_are_found_in_one_call_and_never_proposed_twice():
    """Ten in one light session, given the brief, the README and the tickets.

    What was thrown away goes into the next prompt, and what the model proposes
    again anyway is dropped on the way in. Every batch's cost is written down.
    """
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        board.replace_markdown(project, "Un jeu d'usine en navigateur.")
        done = board.create_row("tickets", "Ajouter le tutoriel", {"Status": "Done"})
        board.update("tickets", done, {"Project": [project]})
        clone = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        (clone / "README.md").write_text("# Usine\n\nConstruire des chaînes de production.\n")
        api = _ideas_api(board)
        api._config.projects["Usine"] = str(clone)

        first = [_idea(f"Idée numéro {word}") for word in (
            "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf"
        )] + [_idea("Ajouter le tutoriel")]
        again = [_idea("Idée numéro un !"), _idea("Une sauvegarde dans le cloud")]
        fake_run, asked = _proposing([first, again])
        original, session.run = session.run, fake_run
        try:
            batch = api.ideas.generate(project)
            listed = api.ideas.proposed(project)
            thrown = listed["ideas"][0]
            api.ideas.discard(thrown["id"])
            second = api.ideas.generate(project)
        finally:
            session.run = original
            shutil.rmtree(clone, ignore_errors=True)

        assert len(asked) == 2, "one call per batch"
        call = asked[0]
        assert call["model"] == "haiku", "a light model unless the file says otherwise"
        assert "Un jeu d'usine en navigateur." in call["prompt"]
        assert "Construire des chaînes de production." in call["prompt"]
        assert "Ajouter le tutoriel (done)" in call["prompt"]
        assert "exactly 10 ideas" in call["prompt"]
        assert '"ticket", always' in call["prompt"]

        assert len(batch["ideas"]) == 9, "a ticket already on the board is not an idea"
        assert batch["dropped"] == ["Ajouter le tutoriel"]
        assert len(listed["ideas"]) == 9 and listed["scope"] == "project"
        assert all(idea["project"] == project.replace("-", "") for idea in listed["ideas"])

        assert thrown["title"] in asked[1]["prompt"], "a thrown idea is named to the model"
        assert [idea["title"] for idea in second["ideas"]] == ["Une sauvegarde dans le cloud"]
        assert second["dropped"] == ["Idée numéro un !"], "and never proposed again"
        assert ideas.get(thrown["id"]).status == "discarded"
        assert thrown["id"] not in [idea["id"] for idea in api.ideas.proposed(project)["ideas"]]
        history = api.ideas.proposed(project)["decided"]
        assert [idea["id"] for idea in history] == [thrown["id"]], "the history holds what was decided"
        assert history[0]["status"] == "discarded"

        with db.transaction(immediate=False) as connection:
            costs = connection.execute(
                "SELECT count, cost_usd FROM idea_batches ORDER BY id"
            ).fetchall()
        assert costs == [(9, 0.02), (1, 0.02)], costs
        assert api.ideas.proposed(project)["cost_usd"] == 0.04
        assert api.ideas.proposed("")["ideas"] == [], "the workspace's ideas are another scope"


@case
def an_idea_turned_into_a_ticket_is_a_draft_and_a_project_idea_a_project():
    """Turned into a ticket: a draft in the tickets database, What / Where / Done when / Out of
    scope, attached to its project, no model. A new project's idea creates the
    project, its description as the brief, and a first ticket to frame it.
    Taking it back proposes it again — and turning it again writes nothing twice."""
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        api._config.runner.ideas_model = "sonnet"
        fake_run, asked = _proposing([
            [_idea("Un mode sombre", where="Les feuilles de style", done=["Le thème bascule"])],
            [_idea("Un site pour le club", "project", description="Les horaires.\nLes inscriptions."),
             _idea("Un journal des coûts", "ticket")],
        ])
        original, session.run = session.run, fake_run
        try:
            mine = api.ideas.generate(project)["ideas"][0]
            general = api.ideas.generate("")["ideas"]
        finally:
            session.run = original
        assert asked[0]["model"] == "sonnet", "the model is a setting"
        assert "Usine" in asked[1]["prompt"], "the workspace is told its projects"
        assert '"project" for a new project' in asked[1]["prompt"]

        settings = api.config.notion
        kept = api.ideas.ticket(mine["id"])
        assert kept["status"] == "ticket" and kept["ticket"]
        ticket = board.page(kept["ticket"])
        assert ticket.title == "Un mode sombre"
        assert store.read(ticket, settings.prop("project")) == [project]
        assert not store.read(ticket, settings.prop("status")), "a draft"
        assert not store.read(ticket, settings.prop("model")), "Model left empty"
        text = board.blocks_text(kept["ticket"])
        for heading in ("## What", "## Where", "## Done when", "## Out of scope"):
            assert heading in text, text
        assert "- [ ] Le thème bascule" in text

        club = next(idea for idea in general if idea["kind"] == "project")
        made = api.ideas.ticket(club["id"])
        assert made["created"], "the project itself"
        assert board.page(made["created"]).title == "Un site pour le club"
        assert "Les inscriptions." in board.blocks_text(made["created"])
        framing = board.page(made["ticket"])
        assert framing.title == "Frame the project Un site pour le club"
        assert store.read(framing, settings.prop("project")) == [made["created"]]
        assert "## Done when" in board.blocks_text(made["ticket"])

        thrown = next(idea for idea in general if idea["kind"] == "ticket")
        assert api.ideas.discard(thrown["id"])["status"] == "discarded"
        tickets_before = len(board.query("tickets"))

        undone = api.ideas.undo()
        assert undone["was"] == "discarded" and undone["idea"]["status"] == "proposed"
        assert len(board.query("tickets")) == tickets_before, "throwing away wrote nothing"
        back = api.ideas.undo("")
        assert back["idea"]["id"] == club["id"] and back["was"] == "ticket"
        assert club["id"] in [idea["id"] for idea in api.ideas.proposed("")["ideas"]]
        again = api.ideas.ticket(club["id"])
        assert (again["ticket"], again["created"]) == (made["ticket"], made["created"])
        assert len(board.query("tickets")) == tickets_before, "turned again, written once"
        assert api.ideas.undo(project)["idea"]["id"] == mine["id"], "a scope's own last choice"
        try:
            api.ideas.undo(project)
        except LookupError:
            pass
        else:
            raise AssertionError("nothing left to take back in this project")


@case
def an_idea_is_kept_thrown_reopened_and_nothing_is_ever_deleted():
    """Keeping writes nothing on the board; throwing away keeps the idea; every
    status is counted, and a ticket must be made new again before it is thrown."""
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        fake_run, _ = _proposing([[_idea("Un mode sombre"), _idea("Un export CSV"), _idea("Un tutoriel")]])
        original, session.run = session.run, fake_run
        try:
            dark, export, tutorial = api.ideas.generate(project)["ideas"]
        finally:
            session.run = original
        tickets_before = len(board.query("tickets"))
        kept = api.ideas.keep(dark["id"])
        assert kept["status"] == "kept" and not kept["ticket"]
        assert len(board.query("tickets")) == tickets_before, "kept is not yet a ticket"
        thrown = api.ideas.discard(export["id"])
        assert thrown["status"] == "discarded" and thrown["decided_at"]
        made = api.ideas.ticket(tutorial["id"])
        try:
            api.ideas.discard(tutorial["id"])
        except ValueError:
            pass
        else:
            raise AssertionError("a ticket is made new again before it is thrown away")

        every = api.ideas.every(project)
        assert every["counts"] == {"proposed": 0, "kept": 1, "discarded": 1, "ticket": 1}
        assert {idea["id"] for idea in every["ideas"]} == {dark["id"], export["id"], tutorial["id"]}

        # The Ideas page asks for every scope at once, the workspace's included.
        api.ideas.write("", "ticket", "Une idée de l'espace")
        everywhere = api.ideas.every(None)
        assert everywhere["scope"] == "all" and len(everywhere["ideas"]) == 4
        assert {idea["project"] for idea in everywhere["ideas"]} == {"", ideas.bare(project)}
        assert everywhere["counts"]["proposed"] == 1

        back = api.ideas.reopen(tutorial["id"])
        assert back["status"] == "proposed" and back["ticket"] == made["ticket"]
        assert back["changed_at"] >= made["changed_at"] and back["decided_at"] is None
        assert api.ideas.discard(tutorial["id"])["status"] == "discarded"
        assert api.ideas.every(project)["counts"]["discarded"] == 2
        assert [idea.title for idea in ideas.listed(project, ("discarded",))] == ["Un export CSV", "Un tutoriel"]


@case
def an_idea_written_by_hand_is_signed_and_never_proposed_again():
    """Origin manual, its author's name and picture; reworded, the editor and the
    moment; Ponos's own say Ponos. And the next batch is told about it."""
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        api.ideas._person = ("Salva", "https://example.com/salva.png")
        written = api.ideas.create(
            {"project": project, "title": "  Une carte  des usines ", "description": "Pour voir.\n\nOù."}
        )
        assert written["origin"] == "manual" and written["status"] == "proposed"
        assert written["title"] == "Une carte des usines"
        assert written["description"] == "Pour voir.\n\nOù.", "a hand-written paragraph keeps its lines"
        assert written["author"] == {"kind": "human", "name": "Salva", "avatar": "https://example.com/salva.png"}
        assert written["edited"] is None and written["kind"] == "ticket"
        assert written["project"] == project.replace("-", "")
        for wrong in ({"project": project, "title": "  "}, {"project": "f" * 32, "title": "Rien"}):
            try:
                api.ideas.create(wrong)
            except (ValueError, LookupError):
                pass
            else:
                raise AssertionError(f"refused: {wrong}")
        workspace = api.ideas.create({"title": "Un site", "kind": "project", "category": "feature"})
        assert workspace["scope"] == "global" and workspace["kind"] == "project"
        assert workspace["category"] == "feature" and written["category"] == ""

        fake_run, asked = _proposing([[_idea("Une carte des usines !"), _idea("Un mode sombre")]])
        original, session.run = session.run, fake_run
        try:
            found = api.ideas.generate(project)
        finally:
            session.run = original
        assert "Une carte des usines" in asked[0]["prompt"], "a hand-written idea is named to the model"
        assert found["dropped"] == ["Une carte des usines !"]
        ponos = found["ideas"][0]
        assert ponos["origin"] == "ponos" and ponos["author"]["kind"] == "ponos"

        api.ideas._person = ("Quelqu'un", "")
        edited = api.ideas.edit(
            ponos["id"], {"title": "Un mode sombre, partout", "description": "Oui.", "category": "ux"}
        )
        assert edited["title"] == "Un mode sombre, partout" and edited["author"]["kind"] == "ponos"
        assert edited["category"] == "ux"
        assert edited["edited"]["name"] == "Quelqu'un" and edited["edited"]["at"]

        db.close()
        assert ideas.get(written["id"]).author == "Salva", "it survives a restart"
        assert len(api.ideas.every(project)["ideas"]) == 2


@case
def the_ideas_kept_before_their_author_was_known_became_tickets():
    """Migration 13 on a file of migration 12: a kept idea had become a ticket,
    and every idea is Ponos's, dated by its last decision."""
    with _state_home():
        location = db.path()
        raw = db.open_at(location, db.MIGRATIONS[:12])
        raw.execute(
            "INSERT INTO ideas (scope, project, kind, title, status, ticket, created_at, decided_at)"
            " VALUES ('project', 'p', 'ticket', 'Gardée', 'kept', 't1', '2026-10-01', '2026-10-02'),"
            " ('project', 'p', 'ticket', 'Jetée', 'discarded', '', '2026-10-01', '2026-10-03'),"
            " ('project', 'p', 'ticket', 'Neuve', 'proposed', '', '2026-10-01', NULL)"
        )
        raw.close()
        db.close()
        found = {idea.title: idea for idea in ideas.every("p")}
        assert found["Gardée"].status == "ticket" and found["Gardée"].ticket == "t1"
        assert found["Jetée"].status == "discarded" and found["Jetée"].changed_at == "2026-10-03"
        assert found["Neuve"].changed_at == "2026-10-01"
        assert all(idea.origin == "ponos" for idea in found.values())


@case
def the_console_writes_a_schedule_without_touching_what_a_pass_writes_back():
    """`Next`, `Last` and `Last ticket` are the runner's, not the form's.

    Letting the console edit them would let somebody make an occurrence happen
    twice, or never — which is the one thing the calendar must not allow.
    """
    with _board() as board:
        api = _markdown_api(board)
        created = api.create_schedule(
            "Revue des dépendances",
            {"cadence": "Weekly", "at": "09:00", "day": "Monday", "active": True},
        )
        row = schedules.read(board.page(created["id"]), board.settings())
        assert row.name == "Revue des dépendances"
        assert (row.cadence, row.at, row.day) == ("Weekly", "09:00", "Monday")
        assert row.active is False, "a new schedule is created unticked, whatever was asked"
        assert not row.problem

        api.save_schedule(created["id"], {"active": True, "at": "07:30", "priority": 80})
        again = schedules.read(board.page(created["id"]), board.settings())
        assert again.active is True and again.at == "07:30" and again.priority == 80
        assert again.next is None and again.last is None

        # The type and the sub-type its tickets are born with, said by their
        # keys and written in the board's words; empty lets them be guessed.
        api.save_schedule(created["id"], {"type": "code", "subtype": "bug"})
        typed = schedules.read(board.page(created["id"]), board.settings())
        assert (typed.kind, typed.subtype) == ("Code", "Bug"), (typed.kind, typed.subtype)
        listed = api.schedules()
        assert listed["schedules"][0]["type"] == "code" and listed["schedules"][0]["subtype"] == "bug"
        assert [choice["value"] for choice in listed["choices"]["type"]] == list(kinds.KINDS)
        api.save_schedule(created["id"], {"type": ""})
        assert schedules.read(board.page(created["id"]), board.settings()).kind == ""
        try:
            api.save_schedule(created["id"], {"type": "poem"})
        except ValueError:
            pass
        else:
            raise AssertionError("a type that is none of the four is refused")

        # What a pass writes back is not the form's to set — so a payload made
        # only of those is refused, rather than quietly doing nothing.
        try:
            api.save_schedule(created["id"], {"next": "2030-01-01", "last": "2030-01-01"})
        except ValueError:
            pass
        else:
            raise AssertionError("a change with nothing to change must say so")
        untouched = schedules.read(board.page(created["id"]), board.settings())
        assert untouched.next is None and untouched.last is None


@case
def the_console_reads_and_rewrites_the_brief_a_schedule_is_born_with():
    """A schedule's page body is copied under every ticket it makes.

    The list leaves it out — twenty rows would be twenty pages read — so one
    schedule opened is the row plus its body, and saving the body alone is a
    change, not a payload with nothing in it.
    """
    with _board() as board:
        api = _markdown_api(board)
        created = api.create_schedule(
            "Revue des dépendances", {"cadence": "Weekly", "body": "Première version."}
        )
        opened = api.schedule(created["id"])
        assert opened["name"] == "Revue des dépendances"
        assert opened["body"] == "Première version."

        api.save_schedule(created["id"], {"body": "## Deuxième\n\n- une liste"})
        assert api.schedule(created["id"])["body"] == "## Deuxième\n\n- une liste"
        api.save_schedule(created["id"], {"body": "## Deuxième\n\n- une liste"})
        assert board.blocks_text(created["id"]) == "## Deuxième\n\n- une liste", (
            "a second save must not stack"
        )
        try:
            api.schedule("f" * 32)
        except LookupError:
            pass
        else:
            raise AssertionError("a schedule that is not there must say so")


@case
def the_console_says_which_board_it_is_looking_at():
    """The panes read it: a Notion link is worth drawing on one and not the other."""
    with _board() as board:
        with _state_home():
            said = _markdown_api(board).state()
    assert said["storage"] == "markdown"
    assert said["board_path"] == str(board.root)


@case
def a_block_reads_back_whichever_end_of_the_wire_it_came_from():
    """`plain` serves two callers, and they hand it two shapes.

    Notion returns a piece of rich text with `plain_text` on it; a block this
    code has just built carries `text.content`. Reading only the first left the
    live report writing a file full of empty bullets.
    """
    built = markdown.to_blocks("- une puce")[0]
    assert "plain_text" not in json.dumps(built), "premise: a built block has no plain_text"
    assert markdown.plain(built) == "- une puce"
    returned = {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"plain_text": "une puce"}]},
    }
    assert markdown.plain(returned) == "- une puce"


@case
def an_image_in_a_brief_is_named_for_the_session_and_drawn_by_the_console():
    """A capture in a Notion brief: no dead link anywhere, a fresh one on demand.

    The line used to carry the file's address cut off its signature, which S3
    answers with 403 from the first second — shown as is on the console, in
    English, crochets and all. It now names the file and the block holding it:
    the session is still told there is a picture, and the console asks the
    board where that block's file is at the moment it draws it.
    """
    signed = "https://prod-files-secure.s3.us-west-2.amazonaws.com/w/f/opoil-bug-prix-negatif.png?X-Amz-Signature=abc"
    block_id = "3ec45168-0af4-8106-be46-dbf34ca5cc95"
    image = {
        "id": block_id,
        "type": "image",
        "image": {
            "type": "file",
            "file": {"url": signed, "expiry_time": "2026-10-01T10:00:00.000Z"},
            "caption": [{"plain_text": "Prix négatif affiché au client"}],
        },
    }
    line = markdown.plain(image)
    assert "amazonaws" not in line and "?" not in line, line
    assert line == f"[image attached to the ticket: Prix négatif affiché au client (Notion block {block_id.replace('-', '')})]"
    read = markdown.ATTACHED.match(line)
    assert read and read["kind"] == "image" and read["block"] == block_id.replace("-", "")
    assert read["label"] == "Prix négatif affiché au client"
    # Without a caption, the file's own name says what it is.
    image["image"]["caption"] = []
    assert markdown.ATTACHED.match(markdown.plain(image))["label"] == "opoil-bug-prix-negatif.png"
    pdf = {"id": "b" * 32, "type": "pdf", "pdf": {"type": "external", "external": {"url": ""}}}
    assert markdown.ATTACHED.match(markdown.plain(pdf))["label"] is None

    client = notion.Client("ntn_x")
    asked: list[str] = []

    def request(method, path, body=None, **_):
        asked.append(path)
        if path == f"/blocks/{'c' * 32}":
            return {"id": "c" * 32, "type": "paragraph", "paragraph": {"rich_text": []}}
        return image

    client._request = request  # type: ignore[method-assign]
    assert client.attachment(block_id.replace("-", "")) == signed
    try:
        client.attachment("c" * 32)
        raise AssertionError("a paragraph holds no file")
    except LookupError:
        pass

    from ponos.web import server as web_server

    api = _bare_api(client)
    console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:

        def get(path: str) -> tuple[int, str]:
            connection = http.client.HTTPConnection("127.0.0.1", console.server_address[1], timeout=5)
            connection.request("GET", path, headers={"Authorization": "Bearer tok"})
            response = connection.getresponse()
            response.read()
            connection.close()
            return response.status, response.getheader("Location") or ""

        # Signed at the moment it is opened, and the browser is sent there.
        assert get(f"/api/files/{block_id}") == (302, signed)
        assert asked[-1] == f"/blocks/{block_id.replace('-', '')}"
        assert get(f"/api/files/{'c' * 32}")[0] == 404
    finally:
        console.shutdown()
        console.server_close()

    # A board of files has no blocks: a line copied from Notion is only a name.
    try:
        files.Board(Path(tempfile.mkdtemp())).attachment(block_id)
        raise AssertionError("a board of files holds no Notion file")
    except LookupError:
        pass


@case
def the_live_report_writes_its_steps_into_the_file():
    """A text file has no fold to hide a session's story in, so it keeps it.

    The toggle's title is the one thing lost — there is no line to rewrite in
    place — and `update_block` says so by doing nothing. What must not happen is
    the report disabling itself: the board's live column comes off the same
    flush, and a Markdown installation would silently stop having one.
    """
    with _board() as board:
        page_id = board.create_row("tickets", "Un ticket", {"Status": "Ready"})
        live = progress.Live(
            board, page_id, database="tickets", property_name="Progress",
            interval=0, words=voice.Voice(""),
        )
        live.add(progress.Step("Read", "src/x.py"))
        live.flush()
        assert store.read(board.page(page_id), "Progress") == "Read · src/x.py"
        live.add(progress.Step("J'ai lu le fichier.", said=True))
        live.flush()
        live.close("Fini.", ok=True)

        assert not live.disabled
        written = board.blocks_text(page_id)
        assert "src/x.py" not in written, written
        assert "J'ai lu le fichier." in written
        # Cleared on the way out, exactly as on a Notion board.
        assert store.read(board.page(page_id), "Progress") == ""


# -- a project's picture -----------------------------------------------------


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _project_page(
    page_id: str = "b" * 32,
    *,
    cover: dict | None = None,
    icon: dict | None = None,
    edited: str = "2026-09-30T08:00:00.000Z",
) -> notion.Page:
    """A project page as Notion hands one over: the pictures are beside the columns."""
    return notion.Page(
        id=page_id, url="", title="Opoil",
        raw={"id": page_id, "cover": cover, "icon": icon, "last_edited_time": edited},
    )


def _notion_file(path: str, signature: str, expires: str = "2026-09-30T09:00:00.000Z") -> dict:
    return {
        "type": "file",
        "file": {
            "url": f"https://prod-files-secure.s3.us-west-2.amazonaws.com/{path}?X-Amz-Signature={signature}",
            "expiry_time": expires,
        },
    }


class _Pictures:
    """A cache of pictures on a clock of the test's own, with a network that counts."""

    def __init__(self, fetched: bytes = JPEG) -> None:
        self.now = datetime(2026, 9, 30, 8, 5, tzinfo=timezone.utc)
        self.fetched: list[str] = []
        self.answer = fetched
        self.directory = Path(tempfile.mkdtemp())
        self.cache = images.Cache(
            self.directory, fetch=self._fetch, clock=lambda: self.now, database=self.directory / "ponos.db"
        )

    def _fetch(self, url: str) -> tuple[bytes, str]:
        self.fetched.append(url)
        return self.answer, "image/jpeg"

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


@contextmanager
def _pictures(fetched: bytes = JPEG):
    pictures = _Pictures(fetched)
    try:
        yield pictures
    finally:
        pictures.close()


def _never(slot: str, picture: store.Picture) -> notion.Page:
    raise AssertionError(f"nothing of ours was waiting, and the {slot} was sent anyway")


@case
def a_project_picture_is_read_in_each_of_its_three_forms():
    """A file Notion keeps, a URL somebody else keeps, an emoji — and never Notion's URL.

    The signature on a Notion file changes with every read of the page, the
    file does not: known by its signature, the same cover would look like a new
    one every ten minutes, and be downloaded again as often.
    """
    first = images.face({"cover": _notion_file("w/f/opoil.png", "one")}, "cover")
    again = images.face({"cover": _notion_file("w/f/opoil.png", "two")}, "cover")
    assert first.kind == "file" and first.expires == "2026-09-30T09:00:00.000Z"
    assert first.identity == again.identity, "a new signature is not a new picture"
    assert first.url != again.url

    unsplash = "https://images.unsplash.com/photo-1?w=1500"
    external = images.face({"cover": {"type": "external", "external": {"url": unsplash}}}, "cover")
    assert (external.kind, external.url) == ("external", unsplash)

    emoji = images.face({"icon": {"type": "emoji", "emoji": "🛢️"}}, "icon")
    assert (emoji.kind, emoji.emoji) == ("emoji", "🛢️")
    assert images.face({"cover": None}, "cover").kind == ""

    with _pictures() as pictures:
        page = _project_page(
            cover=_notion_file("w/f/opoil.png", "one"),
            icon={"type": "emoji", "emoji": "🛢️"},
        )
        pictures.cache.observe(page, _never)
        cover = pictures.cache.shown(page.id, "cover")
        assert cover["kind"] == "image" and cover["version"]
        # What the console is handed is its own address for the picture, built
        # by the API: nothing of Notion's, which would be dead within the hour.
        assert "amazonaws" not in json.dumps(cover), cover
        assert pictures.cache.shown(page.id, "icon") == {"kind": "emoji", "emoji": "🛢️"}

        pictures.cache.observe(
            _project_page(cover={"type": "external", "external": {"url": unsplash}}), _never
        )
        # Somebody else's URL is not a secret, and the dialog shows it back.
        assert pictures.cache.shown(page.id, "cover")["url"] == unsplash
        assert pictures.cache.picture(page.id, "cover", lambda: page)[0] == JPEG
        assert pictures.fetched == [unsplash]


@case
def a_notion_file_is_shown_hours_later_and_fetched_again_only_when_it_may_have_changed():
    """The copy is what is shown; the page's last edit and the URL's hour decide the rest.

    A cover downloaded at nine is still the cover at noon: its URL expired at
    ten, but nothing about the picture did. What makes the copy suspect is the
    page being edited since — and what an expired URL costs is a fresh one,
    asked of the page, never a request Notion's storage would refuse.
    """
    with _pictures() as pictures:
        page = _project_page(cover=_notion_file("w/f/opoil.png", "one"))
        pictures.cache.observe(page, _never)
        assert pictures.cache.picture(page.id, "cover", lambda: page)[0] == JPEG
        assert len(pictures.fetched) == 1

        pictures.now += timedelta(hours=5)
        assert pictures.cache.picture(page.id, "cover", lambda: page)[0] == JPEG
        assert len(pictures.fetched) == 1, "hours later, the copy is still the picture"

        # Edited in Notion: same file name, and possibly another image under it.
        edited = _project_page(
            cover=_notion_file("w/f/opoil.png", "two", expires="2026-09-30T14:30:00.000Z"),
            edited="2026-09-30T13:00:00.000Z",
        )
        pictures.cache.observe(edited, _never)
        assert pictures.cache.picture(page.id, "cover", lambda: edited)[0] == JPEG
        assert pictures.fetched[-1].endswith("two"), pictures.fetched

        # And a URL whose hour is up is never tried: the page gives a new one.
        pictures.now += timedelta(hours=4)
        pictures.cache.observe(
            _project_page(
                cover=_notion_file("w/f/opoil.png", "three", expires="2026-09-30T15:00:00.000Z"),
                edited="2026-09-30T16:00:00.000Z",
            ),
            _never,
        )
        fresh = _project_page(
            cover=_notion_file("w/f/opoil.png", "four", expires="2026-09-30T19:00:00.000Z"),
            edited="2026-09-30T16:00:00.000Z",
        )
        asked: list[str] = []
        pictures.cache.picture(page.id, "cover", lambda: asked.append("page") or fresh)
        assert asked == ["page"], "an expired URL is renewed by reading the page"
        assert pictures.fetched[-1].endswith("four"), pictures.fetched
        assert not any(url.endswith("three") for url in pictures.fetched)


@case
def a_picture_the_console_chose_is_not_read_back_as_a_change():
    """What Notion answers a write with is agreed on at once.

    Otherwise the next reading of the board would find a picture it has never
    agreed on, take it for somebody else's change, and download back the very
    bytes that were just uploaded — or settle a later change against itself.
    """
    with _pictures() as pictures:
        page = _project_page(cover=None)
        pictures.cache.observe(page, _never)
        sent: list[tuple[str, store.Picture]] = []

        def push(slot: str, picture: store.Picture) -> notion.Page:
            sent.append((slot, picture))
            return _project_page(
                cover=_notion_file("w/u/cover.webp", "answer"), edited="2026-09-30T08:05:00.000Z"
            )

        pictures.cache.change(page.id, "cover", store.Picture(data=PNG, type="image/png"), push)
        assert [slot for slot, _ in sent] == ["cover"] and sent[0][1].data == PNG
        assert "pending" not in pictures.cache.shown(page.id, "cover")

        # Read back ten minutes later, with a new signature on the same file.
        again = _project_page(
            cover=_notion_file("w/u/cover.webp", "later"), edited="2026-09-30T08:05:00.000Z"
        )
        pictures.cache.observe(again, _never)
        pictures.cache.observe(again, _never)
        assert len(sent) == 1, "a change is sent once"
        assert pictures.cache.picture(page.id, "cover", lambda: again)[0] == PNG
        assert pictures.fetched == [], "the bytes we uploaded are the copy"
        # And no signed URL is written down: on disk it could only be a dead one.
        with db.transaction(location=pictures.directory / "ponos.db") as connection:
            written = " ".join(entry for (entry,) in connection.execute("SELECT entry FROM images"))
        assert written and "X-Amz-Signature" not in written


@case
def a_picture_notion_refused_is_kept_here_and_sent_again_at_the_next_reading():
    """No network, no right to update the page: the choice is not lost for that.

    It is shown as chosen, with what went wrong, and the next reading of the
    board — the console's own, every few minutes — sends it again.
    """
    with _pictures() as pictures:
        page = _project_page(icon={"type": "emoji", "emoji": "🛢️"})
        pictures.cache.observe(page, _never)

        def refuse(slot: str, picture: store.Picture) -> notion.Page:
            raise notion.NotionError("PATCH /pages/b: 403 Insufficient permissions")

        pictures.cache.change(page.id, "icon", store.Picture(data=PNG, type="image/png"), refuse)
        shown = pictures.cache.shown(page.id, "icon")
        assert shown["kind"] == "image" and shown["pending"], shown
        assert "403" in shown["error"]
        assert pictures.cache.picture(page.id, "icon", lambda: page)[0] == PNG

        sent: list[store.Picture] = []

        def accept(slot: str, picture: store.Picture) -> notion.Page:
            sent.append(picture)
            return _project_page(
                icon=_notion_file("w/u/icon.png", "x"), edited="2026-09-30T08:20:00.000Z"
            )

        pictures.cache.observe(page, accept)
        assert [picture.data for picture in sent] == [PNG]
        shown = pictures.cache.shown(page.id, "icon")
        assert "pending" not in shown and "error" not in shown, shown


@case
def when_both_sides_changed_the_picture_the_newest_wins_and_says_so():
    """A change still waiting here, another made in Notion meanwhile: the later one.

    The console's change carries the moment it was made, Notion's the page's
    last edit. Whichever lost is gone — but not silently: the entry says which
    side won, and the console shows it.
    """
    before = _project_page(cover=_notion_file("w/f/old.png", "a"), edited="2026-09-30T08:00:00.000Z")

    def refuse(slot: str, picture: store.Picture) -> notion.Page:
        raise notion.NotionError("urlopen error [Errno -3] Temporary failure in name resolution")

    # Chosen here at 08:05, changed in Notion at 08:30: Notion's is the newer.
    with _pictures() as pictures:
        pictures.cache.observe(before, _never)
        pictures.cache.change(before.id, "cover", store.Picture(url="https://example.org/a.jpg"), refuse)
        theirs = _project_page(cover=_notion_file("w/f/theirs.png", "b"), edited="2026-09-30T08:30:00.000Z")
        pictures.cache.observe(theirs, _never)
        shown = pictures.cache.shown(before.id, "cover")
        assert shown["conflict"] == "notion" and "pending" not in shown, shown
        assert pictures.cache.entry(before.id, "cover")["agreed"].endswith("theirs.png")

    # Changed in Notion at 08:02, chosen here at 08:05: the console's is the newer.
    with _pictures() as pictures:
        pictures.cache.observe(before, _never)
        pictures.cache.change(before.id, "cover", store.Picture(url="https://example.org/a.jpg"), refuse)
        theirs = _project_page(cover=_notion_file("w/f/theirs.png", "b"), edited="2026-09-30T08:02:00.000Z")
        sent: list[store.Picture] = []

        def accept(slot: str, picture: store.Picture) -> notion.Page:
            sent.append(picture)
            return _project_page(
                cover={"type": "external", "external": {"url": picture.url}},
                edited="2026-09-30T08:10:00.000Z",
            )

        pictures.cache.observe(theirs, accept)
        assert [picture.url for picture in sent] == ["https://example.org/a.jpg"]
        shown = pictures.cache.shown(before.id, "cover")
        assert shown["conflict"] == "console" and "pending" not in shown, shown


@case
def the_notion_client_uploads_a_picture_then_sets_it_on_the_page():
    """The File Upload API, then one PATCH; a URL is attached without being fetched."""
    client = notion.Client("ntn_x")
    calls: list[tuple] = []

    def request(method, path, body=None, *, raw=None, kind="application/json"):
        calls.append((method, path, body, raw, kind))
        if path == "/file_uploads":
            return {"id": "upload-1", "status": "pending"}
        if path.startswith("/pages/"):
            return {"id": "b" * 32, "properties": {}, **body}
        return {"status": "uploaded"}

    client._request = request  # type: ignore[method-assign]
    page = client.set_picture("b" * 32, "cover", store.Picture(data=PNG, type="image/png", name="opoil.png"))
    assert [call[:2] for call in calls] == [
        ("POST", "/file_uploads"),
        ("POST", "/file_uploads/upload-1/send"),
        ("PATCH", f"/pages/{'b' * 32}"),
    ]
    assert calls[0][2] == {"filename": "opoil.png", "content_type": "image/png"}
    sent, kind = calls[1][3], calls[1][4]
    assert kind.startswith("multipart/form-data; boundary=")
    assert PNG in sent and b'name="file"; filename="opoil.png"' in sent
    assert calls[2][2] == {"cover": {"type": "file_upload", "file_upload": {"id": "upload-1"}}}
    assert images.face(page.raw, "cover").identity == "upload:upload-1"

    calls.clear()
    client.set_picture("b" * 32, "icon", store.Picture(emoji="🛢️"))
    client.set_picture("b" * 32, "cover", store.Picture(url="https://example.org/a.jpg"))
    client.set_picture("b" * 32, "icon", store.Picture())
    assert [call[2] for call in calls] == [
        {"icon": {"type": "emoji", "emoji": "🛢️"}},
        {"cover": {"type": "external", "external": {"url": "https://example.org/a.jpg"}}},
        {"icon": None},
    ]
    try:
        client.set_picture("b" * 32, "cover", store.Picture(emoji="🛢️"))
    except notion.NotionError:
        pass
    else:
        raise AssertionError("Notion has no emoji cover, and must not be asked for one")


@case
def a_markdown_project_keeps_its_picture_beside_it():
    """The same gestures on a board of files: the picture is a file next to the page.

    Its name is in the frontmatter, so the directory moves, commits and syncs
    whole — and nothing is downloaded, since there is nowhere to download from.
    """
    with _board() as board:
        page = board.create_row("projects", "Opoil", {})
        api = _markdown_api(board)
        api.all_projects()

        shown = api.set_picture(page, "cover", store.Picture(data=PNG, type="image/png"))
        assert shown["cover"]["kind"] == "image" and "pending" not in shown["cover"], shown
        assert shown["cover"]["src"].startswith(f"/api/projects/{page}/image/cover?v=")
        _, path = board._find(page)
        front, _ = files.parse(path.read_text(encoding="utf-8"))
        assert front["cover"] == f"{path.stem}.cover.png"
        assert (path.parent / front["cover"]).read_bytes() == PNG
        assert api.picture(page, "cover") == (PNG, "image/png")
        # A column is still a column: the picture is the page's, not a property.
        assert "cover" not in board.page(page).properties

        api.set_picture(page, "icon", store.Picture(emoji="🛢️"))
        assert files.parse(path.read_text(encoding="utf-8"))[0]["icon"] == "🛢️"
        rows = {row["id"]: row for row in api.all_projects()["projects"]}
        assert rows[page]["icon"] == {"kind": "emoji", "emoji": "🛢️"}

        api.set_picture(page, "cover", store.Picture())
        assert "cover" not in files.parse(path.read_text(encoding="utf-8"))[0]
        assert not list(path.parent.glob("*.cover.*")), "the file it replaced goes with it"

        # A frontmatter is not a way to serve whatever the path leads to.
        text = path.read_text(encoding="utf-8").replace("icon: 🛢️", "icon: ../../../etc/passwd")
        path.write_text(text, encoding="utf-8")
        assert board.page(page).raw["icon"] is None


@case
def the_console_serves_a_picture_as_a_picture_and_never_as_a_page():
    """An SVG opened at the console's own address must not be a page with a script."""
    routes = (ROOT / "src/ponos/web/server.py").read_text(encoding="utf-8")
    assert "sandbox" in routes and "PICTURE_POLICY" in routes
    assert images.sniff(b"<svg xmlns='http://www.w3.org/2000/svg'/>") == "image/svg+xml"
    assert images.sniff(b"<html><script>") == ""
    assert images.sniff(PNG, "application/octet-stream") == "image/png"


# -- the console and Notion, kept in step ------------------------------------

from ponos.web import board as web_board  # noqa: E402


class _Minutes:
    """A tickets database whose clock, like Notion's, is kept to the minute.

    Queries answer the `last_edited_time` filter the console builds; `update`
    and `page` are what a move from the console reads and writes. `stale` is a
    query index that has not caught up with the last write yet — measured on the
    real board, one to four seconds after the `PATCH` answered.
    """

    def __init__(self, count: int = 3) -> None:
        self.now = datetime(2026, 9, 30, 9, 32, 6, tzinfo=timezone.utc)
        self.pages: dict[str, store.Page] = {}
        self.queried: list[dict | None] = []
        self.patched: list[tuple[str, dict]] = []
        self.stale: dict[str, store.Page] = {}
        for index in range(count):
            self.add(f"{index + 1:032x}", f"ticket {index + 1}", "done")

    def minute(self) -> str:
        return self.now.replace(second=0, microsecond=0).isoformat().replace("+00:00", ".000Z")

    def add(self, page_id: str, title: str, status: str) -> None:
        self.pages[page_id] = store.Page(
            id=page_id, url="", title=title,
            properties={"Status": store.written("select", status)},
            raw={"last_edited_time": self.minute()},
        )

    def move(self, page_id: str, status: str) -> None:
        """Somebody drags a card in Notion."""
        page = self.pages[page_id]
        self.pages[page_id] = store.Page(
            id=page.id, url="", title=page.title,
            properties={**page.properties, "Status": store.written("select", status)},
            raw={"last_edited_time": self.minute()},
        )

    def query(self, database_id, filter_=None):
        self.queried.append(filter_)
        pages = [self.stale.get(key, page) for key, page in self.pages.items()]
        since = ((filter_ or {}).get("last_edited_time") or {}).get("on_or_after")
        if since:
            floor = datetime.fromisoformat(since)
            pages = [
                page for page in pages
                if datetime.fromisoformat(page.raw["last_edited_time"].replace("Z", "+00:00")) >= floor
            ]
        return pages

    def page(self, page_id):
        return self.pages[page_id.replace("-", "")]

    def update(self, database_id, page_id, values):
        self.patched.append((page_id, values))
        self.move(page_id, values["Status"])


def _reader(fake: _Minutes, said: list) -> web_board.Reader:
    return web_board.Reader(
        clock=lambda: fake.now.timestamp(), journal=lambda report: said.extend(report.entries)
    )


def _statuses(pages) -> dict[str, str]:
    return {page.title: store.read(page, "Status") for page in pages}


@case
def three_moves_in_one_notion_minute_all_reach_the_console():
    """Notion keeps `last_edited_time` to the minute; the console must not care.

    Measured on the real board: four statuses written at :06, :22, :39 and :52
    all came back as `09:32:00.000Z`. A read of "edited since my last read"
    starts inside that minute and would skip all but the first. The window
    reaches two minutes back instead, and every change is seen — and written in
    the journal with when it was made and when it was seen.
    """
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "done"
    assert fake.queried[-1] is None, "the first read is the whole board"

    for second, status in ((22, "blocked"), (39, "review"), (52, "done")):
        fake.now = fake.now.replace(second=second)
        fake.move("1".zfill(32), status)
        assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == status
        window = fake.queried[-1]["last_edited_time"]["on_or_after"]
        assert datetime.fromisoformat(window) < fake.now.replace(second=0), (
            "the window starts before the minute Notion rounds to"
        )
    seen = [entry.detail.split(" · ")[0] for entry in said if entry.what == "seen"]
    assert seen == ["done → blocked", "blocked → review", "review → done"], seen
    assert all("seen 09:32:" in entry.detail for entry in said if entry.what == "seen")

    # The overlap brings the same pages back; the same page is not news.
    fake.now = fake.now.replace(second=58)
    reader.read(fake, "db", "Status")
    assert len([entry for entry in said if entry.what == "seen"]) == 3


@case
def the_whole_board_is_read_again_and_what_the_window_missed_is_counted():
    """Every five minutes, the full read — and an écart is shown, not hidden."""
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    reader.read(fake, "db", "Status")
    # A page whose edit time the window cannot see: as if Notion's clock lied.
    fake.move("1".zfill(32), "blocked")
    fake.pages["1".zfill(32)].raw["last_edited_time"] = "2026-09-30T08:00:00.000Z"
    fake.now = fake.now + timedelta(seconds=30)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "done", "premise"

    fake.now = fake.now + timedelta(seconds=web_board.RECONCILE)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "blocked"
    assert fake.queried[-1] is None, "the reconciliation reads everything"
    assert reader.drift == [
        {"id": "1".zfill(32), "title": "ticket 1", "held": "done", "truth": "blocked"}
    ], reader.drift
    assert any(entry.what == "drift" for entry in said)
    assert web_board.describe(reader, [])["drift"] == 1

    # "Resynchronise now" makes the very next read a full one.
    reader.reconcile_next()
    fake.now = fake.now + timedelta(seconds=5)
    reader.read(fake, "db", "Status")
    assert fake.queried[-1] is None and reader.drift == []


@case
def a_board_of_more_than_a_hundred_tickets_is_read_to_its_last_page():
    """Notion hands out a hundred at a time; the real board is 366 tickets."""
    client = notion.Client("ntn_x")
    asked: list[dict] = []

    def answer(method, path, body=None):
        asked.append(dict(body or {}))
        start = int((body or {}).get("start_cursor") or 0)
        results = [
            {"object": "page", "id": f"{index:032x}", "properties": {}}
            for index in range(start, min(start + 100, 250))
        ]
        more = start + 100 < 250
        return {"results": results, "has_more": more, "next_cursor": str(start + 100) if more else None}

    client._request = answer  # type: ignore[method-assign]
    pages = client.query("db")
    assert len(pages) == 250 and len({page.id for page in pages}) == 250
    assert [one.get("start_cursor") for one in asked] == [None, "100", "200"]
    assert all(one["page_size"] == 100 for one in asked)


@case
def a_move_the_network_lost_is_sent_again_until_notion_has_it():
    """Never lost in silence: pending on the card, then there, or said failed."""
    fake, said = _Minutes(), []
    now = [fake.now.timestamp()]
    outbox = web_board.Outbox(clock=lambda: now[0], journal=lambda report: said.extend(report.entries))
    failures = [store.StoreError("PATCH /pages/x: <urlopen error timed out>")] * 2

    def send(write):
        if failures:
            raise failures.pop()
        return web_board.send(fake, "db", "Status", write)

    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    changed: list[int] = []
    outbox.flush(send, lambda: changed.append(1))
    mark = outbox.marks()["1".zfill(32)]
    assert mark.state == "pending" and "timed out" in mark.error and mark.attempts == 1
    card = web_board.overlay({"status": "done", "column": "done"}, mark, lambda status: status)
    assert card["column"] == "blocked" and card["sync"] == "pending", "drawn where it is going"
    assert fake.patched == []

    outbox.flush(send, lambda: changed.append(1))
    assert outbox.marks()["1".zfill(32)].attempts == 1, "not before its wait is over"
    now[0] += web_board.BACKOFF[0]
    outbox.flush(send, lambda: changed.append(1))
    now[0] += web_board.BACKOFF[1]
    outbox.flush(send, lambda: changed.append(1))
    assert outbox.marks() == {}, "confirmed, and let go of"
    assert store.read(fake.page("1".zfill(32)), "Status") == "blocked"
    assert [entry.what for entry in said] == ["console→notion"]
    assert "3 attempt(s)" in said[0].detail


@case
def a_move_notion_refuses_for_good_is_said_on_the_card_and_tried_again_on_demand():
    fake, said = _Minutes(), []
    outbox = web_board.Outbox(clock=lambda: fake.now.timestamp(), journal=lambda r: said.extend(r.entries))

    def refused(write):
        raise store.StoreError("PATCH /pages/x: 400 blocked is not an option of Status")

    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    outbox.flush(refused, lambda: None)
    mark = outbox.marks()["1".zfill(32)]
    assert mark.state == "failed", "a 400 is not retried: the request itself is wrong"
    card = web_board.overlay({"status": "done", "column": "done"}, mark, lambda status: status)
    assert card["column"] == "done" and card["sync"] == "failed" and "400" in card["sync_error"]
    assert [entry.what for entry in said] == ["write-failed"]

    outbox.retry()
    assert outbox.marks()["1".zfill(32)].state == "pending"
    outbox.flush(lambda write: web_board.send(fake, "db", "Status", write), lambda: None)
    assert outbox.marks() == {}


@case
def a_move_over_a_status_changed_in_notion_meanwhile_is_not_written():
    """The console showed done; somebody moved it to review in Notion since."""
    fake, said = _Minutes(), []
    outbox = web_board.Outbox(clock=lambda: fake.now.timestamp(), journal=lambda r: said.extend(r.entries))
    fake.move("1".zfill(32), "review")
    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done", title="ticket 1"))
    outbox.flush(lambda write: web_board.send(fake, "db", "Status", write), lambda: None)
    assert fake.patched == [], "Notion's review was not written over"
    mark = outbox.marks()["1".zfill(32)]
    assert mark.state == "conflict" and "review" in mark.error
    assert [entry.what for entry in said] == ["conflict"] and "review" in said[0].detail
    card = web_board.overlay({"status": "review", "column": "review"}, mark, lambda status: status)
    assert card["column"] == "review" and card["sync"] == "conflict"

    # Seen, and let go of: a resynchronisation drops it rather than forcing it.
    outbox.retry()
    assert outbox.marks() == {} and fake.patched == []


@case
def a_write_is_confirmed_by_reading_the_page_back():
    fake = _Minutes()
    fake.update = lambda database, page_id, values: fake.patched.append((page_id, values))  # type: ignore[method-assign]
    try:
        web_board.send(fake, "db", "Status", web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    except store.StoreError as error:
        assert "still says done" in str(error)
    else:
        raise AssertionError("a PATCH Notion did not keep is not a move")


@case
def a_confirmed_move_is_not_undone_by_a_query_that_has_not_caught_up():
    """The query index lags a write by seconds: the page read back outranks it."""
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    reader.read(fake, "db", "Status")
    stale = fake.pages["1".zfill(32)]
    confirmed = web_board.send(fake, "db", "Status", web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    reader.hold(confirmed)
    fake.stale["1".zfill(32)] = stale
    fake.now = fake.now + timedelta(seconds=3)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "blocked"
    # Once the hold is over, Notion's word is the word again.
    fake.now = fake.now + timedelta(seconds=web_board.HOLD + 1)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "done"


@case
def reading_the_board_never_writes_to_it():
    """No loop: a move is written once, however many reads and flushes follow."""
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    outbox = web_board.Outbox(clock=lambda: fake.now.timestamp(), journal=lambda r: said.extend(r.entries))
    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    for _ in range(5):
        outbox.flush(lambda write: reader.hold(web_board.send(fake, "db", "Status", write)), lambda: None)
        reader.read(fake, "db", "Status")
        fake.now = fake.now + timedelta(seconds=20)
    fake.now = fake.now + timedelta(seconds=web_board.RECONCILE)
    reader.read(fake, "db", "Status")
    assert len(fake.patched) == 1, fake.patched

    # A move to where the page already is goes out as no write at all.
    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="blocked"))
    outbox.flush(lambda write: web_board.send(fake, "db", "Status", write), lambda: None)
    assert len(fake.patched) == 1 and outbox.marks() == {}


@case
def a_move_waiting_to_be_sent_survives_a_console_restart():
    directory = Path(tempfile.mkdtemp())
    try:
        first = web_board.Outbox(directory / "outbox.json")
        first.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
        again = web_board.Outbox(directory / "outbox.json")
        assert again.marks()["1".zfill(32)].status == "blocked"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _Nudged:
    def __init__(self) -> None:
        self.count = 0

    def nudge(self) -> None:
        self.count += 1


@case
def a_card_moved_from_the_console_is_drawn_waiting_until_notion_has_it():
    """The board the stream carries says it, so every tab says the same thing."""
    api = _bare_api(_ColumnsClient(["Ready", "Done"]))
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    api._outbox = web_board.Outbox(journal=lambda report: None)
    api.watch = _Nudged()
    api.board()
    answer = api.set_status("00000001-0000-0000-0000-000000000000", "review")
    assert answer["sync"] == "pending" and api.watch.count == 1
    write = api._outbox.marks()["00000001000000000000000000000000"]
    assert write.seen == "Done", "what the console showed is what must still be there"
    card = [item for item in api.board()["tickets"] if item["title"] == "ticket 1"][0]
    assert card["column"] == "review" and card["sync"] == "pending", card
    assert api.synchronised()["pending"] == 1 and api.synchronised()["synced_at"]


@case
def a_run_does_not_write_its_verdict_over_a_status_moved_by_hand():
    """Half an hour of session, and you moved the ticket to done meanwhile.

    The run's verdict is not written over yours: the status is left alone, said
    in the journal (where the console finds it and marks the card), and the
    rest of what the run writes — its cost, its session — still goes in.
    """
    status = {"ready": "Ready", "running": "In progress", "review": "In review", "done": "Done"}
    page = _reviewed("a" * 32, "In progress", None)
    with _state_home():
        runner = _board_runner([page], status)
        ticket = ticket_module.Ticket(page)
        moved = _reviewed("a" * 32, "Done", None)
        runner.client.page = lambda page_id: moved  # type: ignore[method-assign]
        runner._set(ticket, **{"Status": "In review", "Pull Request": "https://github.com/o/r/pull/1"})
        assert runner.client.written == [("a" * 32, {"Pull Request": "https://github.com/o/r/pull/1"})]
        entries = sync.journal()
        assert [entry["what"] for entry in entries] == ["conflict"], entries
        assert "Done" in entries[0]["detail"] and "In review" in entries[0]["detail"]

        # The card wears it until somebody edits the page again, in a later minute.
        card = {"id": "a" * 32, "edited": entries[0]["at"]}
        assert web_board.settled(card, web_board.conflicts(entries)["a" * 32])["sync"] == "conflict"
        later = {"id": "a" * 32, "edited": "2099-01-01T00:00:00.000Z"}
        assert "sync" not in web_board.settled(later, web_board.conflicts(entries)["a" * 32])

        # What the run now holds is the page as it is: its next write is judged
        # against Done, and a status written where the page already is is fine.
        runner._set(ticket, **{"Status": "Done"})
        assert runner.client.written[-1] == ("a" * 32, {"Status": "Done"})

    # And a run whose ticket nobody touched writes its verdict as it always did.
    with _state_home():
        page = _reviewed("b" * 32, "In progress", None)
        runner = _board_runner([page], status)
        runner._set(ticket_module.Ticket(page), **{"Status": "In review"})
        assert runner.client.written == [("b" * 32, {"Status": "In review"})]
        assert sync.journal() == []


@case
def a_notion_page_edited_twice_in_one_minute_reaches_the_files_both_times():
    """The Markdown mirror trusted the minute, and lost the second edit of it."""
    with _state_home(), _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)
        minute = (datetime.now(timezone.utc) + timedelta(days=1)).replace(second=0, microsecond=0)
        at = minute.isoformat().replace("+00:00", ".000Z")
        here.update("tickets", page_id, {"Status": "Blocked"}, at=at)
        assert [entry.what for entry in both.synchronise(_settings(), stamps=marks).carried] == ["notion→markdown"]
        here.update("tickets", page_id, {"Status": "Done"}, at=at)
        again = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in again.carried] == ["notion→markdown"], again.entries
        assert store.read(there.page(page_id), "Status") == "Done"
        assert not both.synchronise(_settings(), stamps=marks).carried, "and then nothing"


@case
def a_blocked_ticket_on_a_board_where_failed_is_blocked_too_is_drawn_in_blocked():
    """The 30/09 board: Notion showed three blocked tickets, the console none.

    `failed = blocked = "blocked"` draws one column, the first — and the tickets
    went to the second, which was never drawn.
    """
    api = _bare_api(_ColumnsClient(["blocked", "blocked", "Done"]))
    api._config.notion.status = {**api._config.notion.status, "blocked": "blocked", "failed": "blocked"}
    api._runner._workspace = type("W", (), {"projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    board = api.board()
    drawn = [column["key"] for column in board["columns"]]
    assert "blocked" in drawn and "failed" not in drawn, drawn
    assert [item["column"] for item in board["tickets"]][:2] == ["blocked", "blocked"]
    assert all(item["column"] in drawn for item in board["tickets"]), "no card off the board"



# -- the rename: an installation from before Ponos was called Ponos -----------
# Every old name below is the migration filet under test: what an existing
# installation carries, and what it must not lose.


@case
def an_installation_from_before_the_rename_starts_with_everything_it_had():
    """Old directories, old variables, an old worktree: the first launch moves them all."""
    home = Path(tempfile.mkdtemp())
    old_config = home / ".config" / legacy.OLD
    old_state = home / ".local" / "state" / legacy.OLD
    old_config.mkdir(parents=True)
    (old_config / "config.toml").write_text(
        f'[storage]\nmode = "markdown"\npath = "~/.local/state/{legacy.OLD}/board"\n'
    )
    (old_state / "board").mkdir(parents=True)
    (old_state / "history.jsonl").write_text(
        json.dumps({"at": "2026-09-30T10:00:00+00:00", "status": "done", "ticket": "Fix the footer"}) + "\n"
    )
    repository = home / "workspace" / "app"
    repository.mkdir(parents=True)
    git = lambda *argv, cwd=repository: subprocess.run(  # noqa: E731
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    ).stdout
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "start")
    worktree = old_state / "worktrees" / "app-1234abcd"
    git("worktree", "add", "-q", "-b", "ticket/x", str(worktree))
    slug = session.project_key(worktree)
    (home / ".claude" / "projects" / slug).mkdir(parents=True)
    (home / ".claude" / "projects" / slug / "s1.jsonl").write_text("{}\n")

    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("XDG_", "PONOS_", legacy.OLD_PREFIX))}
    # Said explicitly, where the installation finds it by itself: launched
    # from this checkout, Ponos would not write a state it was not given.
    environment.update(HOME=str(home), PYTHONPATH=str(ROOT / "src"),
                       XDG_STATE_HOME=str(home / ".local" / "state"),
                       **{legacy.OLD_PREFIX + "WEB_EMAIL": "me@example.com"})
    done = subprocess.run([sys.executable, "-m", "ponos", "history"], env=environment,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "Fix the footer" in done.stdout, "the history came along"
    assert "PONOS_WEB_EMAIL" in done.stderr, "the old variable is read, and said to be renamed"
    assert "moved" in done.stderr, "and the move is said in one line"
    state = home / ".local" / "state" / "ponos"
    assert not old_config.exists() and not old_state.exists()
    assert (state / "board").is_dir()
    assert (state / "ponos.db").is_file() and (state / "history.jsonl.imported").is_file(), (
        "moved first, then read into the database"
    )
    assert "~/.local/state/ponos/board" in (home / ".config" / "ponos" / "config.toml").read_text()
    moved = state / "worktrees" / "app-1234abcd"
    assert str(moved) in git("worktree", "list"), "the repository knows where its worktree went"
    assert (home / ".claude" / "projects" / session.project_key(moved) / "s1.jsonl").is_file()

    again = subprocess.run([sys.executable, "-m", "ponos", "history"], env=environment,
                           capture_output=True, text=True, timeout=60)
    assert again.returncode == 0 and "moved" not in again.stderr, "and only once"



@case
def an_old_state_directory_holding_only_a_console_token_is_tidied_once_and_silently():
    """Recreated by an old checkout's test suite, with nothing but an empty
    `logs` and a `web/token` in it: the new state already has its own, and the
    line « was left in place » came back on every command, every ten seconds."""
    home = Path(tempfile.mkdtemp())
    old = home / "state" / legacy.OLD
    new = home / "state" / "ponos"
    (old / "logs").mkdir(parents=True)
    (old / "web").mkdir()
    (old / "web" / "token").write_text("stale\n")
    (new / "logs").mkdir(parents=True)
    (new / "web").mkdir()
    (new / "web" / "token").write_text("in use\n")
    said: list[str] = []
    previous = {key: os.environ.get(key) for key in ("XDG_STATE_HOME", "XDG_CONFIG_HOME")}
    os.environ.update(XDG_STATE_HOME=str(home / "state"), XDG_CONFIG_HOME=str(home / "config"))
    try:
        legacy.directories(said.append)
        assert said == [], said
        assert not old.exists(), "gone, so the next command has nothing to say"
        assert (new / "web" / "token").read_text() == "in use\n", "the token in use is kept"

        # Without a token of its own, the new state takes the old one, as quietly.
        (old / "web").mkdir(parents=True)
        (old / "web" / "token").write_text("stale\n")
        shutil.rmtree(new / "web")
        legacy.directories(said.append)
        assert said == [] and not old.exists()
        assert (new / "web" / "token").read_text() == "stale\n"

        # Something that matters is still moved and said, as before.
        (old / "board").mkdir(parents=True)
        (old / "board" / "fix-the-footer.md").write_text("# Fix the footer\n")
        legacy.directories(said.append)
        assert (new / "board").is_dir() and len(said) == 1 and "moved" in said[0]
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@case
def an_old_variable_is_read_under_its_new_name_unless_the_new_one_is_set():
    environment = {legacy.OLD_PREFIX + "CONFIG": "/old", legacy.OLD_PREFIX + "TERMINAL": "kitty",
                   "PONOS_TERMINAL": "foot"}
    assert legacy.environment(environment) == [legacy.OLD_PREFIX + "CONFIG"]
    assert environment["PONOS_CONFIG"] == "/old"
    assert environment["PONOS_TERMINAL"] == "foot", "the new name wins"


@case
def an_old_session_link_opens_the_worktree_where_it_went():
    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = "/srv/state"
    try:
        assert legacy.path(f"/srv/state/{legacy.OLD}/worktrees/app-1") == "/srv/state/ponos/worktrees/app-1"
        assert legacy.path("/home/me/work/app") == "/home/me/work/app"
    finally:
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous


@case
def the_old_command_says_it_was_renamed_and_runs_ponos():
    directory = Path(tempfile.mkdtemp())
    target = directory / "ponos"
    target.write_text("#!/bin/sh\necho \"ponos $*\"\n")
    target.chmod(0o755)
    alias = directory / "old"
    alias.write_text((ROOT / "bin" / "former-name.in").read_text().replace("@BIN@", str(target)))
    alias.chmod(0o755)
    done = subprocess.run([str(alias), "list", "--all"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0
    assert "renamed ponos" in done.stderr
    assert done.stdout.strip() == "ponos list --all"


@case
def a_ticket_this_machine_took_before_the_rename_is_still_its_own():
    runner = object.__new__(Runner)
    runner._journals = {}
    runner.agent_label = "ponos@laptop"
    assert f"{legacy.OLD}@laptop" in runner.agent_labels
    assert f"{legacy.OLD}@desktop" not in runner.agent_labels


# -- the local database ------------------------------------------------------


@case
def a_new_database_is_brought_to_the_current_schema():
    with _state_home() as home:
        try:
            location, found, disorder = db.check()
            assert location == home / "ponos.db"
            assert found == len(db.MIGRATIONS) >= 1
            assert disorder == ""
            connection = db.connect()
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert {"runs", "steps"} <= tables, tables
            assert location.stat().st_mode & 0o777 == 0o600
            with db.transaction() as writing:
                run = writing.execute(
                    "INSERT INTO runs (ticket, started_at) VALUES ('abc', '2026-10-02T10:00:00+00:00')"
                ).lastrowid
                writing.execute(
                    "INSERT INTO steps (run, position, at, kind) VALUES (?, 1, '2026-10-02T10:00:01+00:00', 'text')",
                    (run,),
                )
            with db.transaction(immediate=False) as reading:
                assert reading.execute("SELECT status FROM runs").fetchone()[0] is None, "running: no status yet"
            assert db.connect() is connection, "one connection per process"
        finally:
            db.close()


@case
def a_database_one_migration_behind_is_brought_up_to_date():
    """Faked with one more migration than the code has."""
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    db.open_at(location).close()

    def notes(connection):
        connection.execute("CREATE TABLE notes (text TEXT)")

    upgraded = db.open_at(location, (*db.MIGRATIONS, notes))
    try:
        assert db.version(upgraded) == len(db.MIGRATIONS) + 1
        upgraded.execute("INSERT INTO notes VALUES ('kept')")
    finally:
        upgraded.close()
    again = db.open_at(location, (*db.MIGRATIONS, notes))
    try:
        assert again.execute("SELECT text FROM notes").fetchall() == [("kept",)], "applied once, not twice"
    finally:
        again.close()


@case
def a_migration_that_fails_leaves_the_file_as_it_was():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    db.open_at(location).close()

    def broken(connection):
        connection.execute("CREATE TABLE half (x)")
        raise RuntimeError("halfway")

    try:
        db.open_at(location, (*db.MIGRATIONS, broken))
    except RuntimeError:
        pass
    else:
        raise AssertionError("the failure must reach the caller")
    connection = db.open_at(location)
    try:
        assert db.version(connection) == len(db.MIGRATIONS)
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'half'").fetchall()
    finally:
        connection.close()


@case
def two_processes_opening_a_new_database_together_both_get_it():
    """The timer and the console start at once: one migrates, the other finds it done."""
    home = tempfile.mkdtemp()
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from ponos import db;"
        "conn = db.connect();"
        "[conn.execute(\"INSERT INTO runs (ticket, started_at) VALUES ('t', 'now')\") for _ in range(50)];"
        "print(db.version(conn))"
    )
    environment = {**os.environ, "XDG_STATE_HOME": home}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(ROOT / "src")],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(4)
    ]
    for process in processes:
        out, err = process.communicate(timeout=60)
        assert process.returncode == 0, err
        assert out.strip() == str(len(db.MIGRATIONS)), out
    connection = db.open_at(Path(home) / "ponos" / "ponos.db")
    try:
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 200
    finally:
        connection.close()


def _json_installation(state_home: Path) -> dict:
    """The state directory of an installation from before the database, filled in.

    What each file holds is handed back, to be found again once it is a table.
    """
    state_home.mkdir(parents=True, exist_ok=True)
    history = [
        {"at": "2026-09-28T09:00:00+00:00", "ticket": "Fix the footer", "id": "a" * 32,
         "status": "done", "project": "app", "seconds": 312.4, "cost_usd": 1.25,
         "pull_request": "https://github.com/o/r/pull/7", "merged": "https://github.com/o/r/pull/7"},
        {"at": "2026-09-29T14:30:00+00:00", "ticket": "Write the guide", "id": "b" * 32,
         "status": "done", "kind": "document", "project": "docs", "cost_usd": 0.5},
        {"at": "2026-09-30T08:00:00+00:00", "ticket": "Flaky", "id": "c" * 32,
         "status": "failed", "reason": "tests red"},
    ]
    (state_home / "history.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in history[:2])
        + "half a line of jso\n"
        + json.dumps(history[2]) + "\n"
    )
    claims = {"a" * 32: "Validated", "d" * 32: "Ready"}
    (state_home / "claims.json").write_text(json.dumps(claims))
    (state_home / "rebases.json").write_text(json.dumps({"a" * 32: 2}))
    (state_home / "conversations.json").write_text(json.dumps({
        "pages": {"e" * 32: "2026-09-30T10:00:00+00:00", "f" * 32: "2026-09-29T10:00:00+00:00"},
        "threads": {"d1": {"session": "s-1", "answered": "c-42", "at": "2026-09-30T10:00:00+00:00"}},
        "cursor": 3,
        "at": 1790000000.5,
    }))
    later = time.time() + 3600
    (state_home / "credits.json").write_text(json.dumps({"until": later, "since": time.time()}))
    (state_home / "reserve.json").write_text(json.dumps({"until": later + 60, "since": time.time()}))
    (state_home / "sync.json").write_text(json.dumps({
        "p1": ["2026-09-30T10:00:00.000Z", "2026-09-30T10:00:01+00:00", "f1ngerpr1nt"],
        "p2": ["2026-09-29T10:00:00.000Z", "2026-09-29T10:00:01+00:00"],
    }))
    journal = [
        {"at": "2026-09-30T10:00:00+00:00", "what": "conflict", "collection": "tickets",
         "page": "p1", "title": "Le ticket", "detail": "both moved"},
        {"at": "2026-09-30T10:05:00+00:00", "what": "seen", "collection": "tickets",
         "page": "p2", "title": "L'autre", "detail": ""},
    ]
    (state_home / "sync.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in journal))
    (state_home / "images").mkdir()
    pictures = {f"{'e' * 32}:cover": {"agreed": "emoji:🐾", "kind": "emoji", "url": ""}}
    (state_home / "images" / "index.json").write_text(json.dumps(pictures, ensure_ascii=False))
    return {
        "history": history, "claims": claims, "journal": journal, "pictures": pictures,
        "files": sorted(path.relative_to(state_home) for path in state_home.rglob("*.json*")),
    }


@case
def an_installation_of_json_files_starts_on_the_database_with_everything_it_had():
    """Same statistics, same conversations, same claims — and the files set aside, not deleted.

    Four processes open it at once, as the timer and the console do after an
    update: the files are read in once, not four times.
    """
    with _state_home() as home:
        try:
            had = _json_installation(home)
            originals = {name: (home / name).read_bytes() for name in had["files"]}
            script = (
                "import sys; sys.path.insert(0, sys.argv[1]);"
                "from ponos import db; print(db.version(db.connect()))"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script, str(ROOT / "src")],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for _ in range(4)
            ]
            for process in processes:
                out, err = process.communicate(timeout=60)
                assert process.returncode == 0, err
                assert out.strip() == str(len(db.MIGRATIONS)), out

            # Migration 17 gives every stop its cause, read back from its sentence.
            coded = [
                {**entry, "code": "unknown"} if entry.get("status") == "failed" else entry
                for entry in had["history"]
            ]
            assert state.history(1_000_000) == coded, "every whole line, in order, once"
            assert state.history(1) == coded[-1:]
            first, last = date(2026, 9, 1), date(2026, 9, 30)
            assert web_statistics.figures([], state.history(1_000_000), first, last) == (
                web_statistics.figures([], had["history"], first, last)
            ), "the same statistics"
            with db.transaction(immediate=False) as connection:
                spent = connection.execute(
                    "SELECT project, sum(cost_usd) FROM history GROUP BY project ORDER BY project"
                ).fetchall()
            assert spent == [("", None), ("app", 1.25), ("docs", 0.5)], spent

            assert state.claims() == had["claims"], "the same claims"
            assert state.rebases("a" * 32) == 2 and state.rebased("a" * 32) == 3

            ledger = conversation.Ledger.load()
            assert ledger.known_pages() == ["e" * 32, "f" * 32], "the same conversations"
            assert ledger.session_of("d1") == "s-1" and ledger.answered("d1") == "c-42"
            assert ledger.cursor == 3 and ledger.at == 1790000000.5

            assert credits.held() > time.time() and credits.held(what="reserve") > credits.held()

            stamps = sync.Stamps()
            assert stamps.seen("p1") and stamps.printed("p1") == "f1ngerpr1nt"
            assert stamps.notion("p2") == "2026-09-29T10:00:00.000Z" and stamps.printed("p2") == ""
            assert sync.journal() == had["journal"]

            pictures = images.Cache(home / "images")
            assert pictures.entry("e" * 32, "cover") == had["pictures"][f"{'e' * 32}:cover"]

            for name, content in originals.items():
                assert not (home / name).exists(), f"{name} is no longer where it was read"
                kept = home / name.with_name(name.name + ".imported")
                assert kept.read_bytes() == content, f"{name} is set aside whole, never deleted"
        finally:
            db.close()


@case
def a_new_installation_has_nothing_to_import_and_nothing_to_set_aside():
    with _state_home() as home:
        try:
            assert state.history() == [] and state.claims() == {} and sync.journal() == []
            assert conversation.Ledger.load().known_pages() == [] and credits.held() == 0.0
            assert sorted(path.name for path in home.iterdir() if ".imported" in path.name) == []
        finally:
            db.close()


@case
def a_database_newer_than_the_code_is_refused_untouched():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    newer = len(db.MIGRATIONS) + 3
    raw = sqlite3.connect(location)
    raw.execute(f"PRAGMA user_version = {newer}")
    raw.close()
    try:
        db.open_at(location)
    except db.TooNew as error:
        message = str(error)
        assert f"version {newer}" in message and f"up to {len(db.MIGRATIONS)}" in message, message
        assert "ponos update" in message
    else:
        raise AssertionError("a newer file must be refused")
    raw = sqlite3.connect(location)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == newer
        assert not raw.execute("SELECT 1 FROM sqlite_master").fetchall(), "nothing created"
    finally:
        raw.close()


@case
def doctor_says_the_database_version_and_refuses_a_newer_one():
    from ponos.__main__ import _doctor_database

    with _state_home() as home:
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert _doctor_database() == 0
            assert f"schema version {len(db.MIGRATIONS)} of {len(db.MIGRATIONS)}" in out.getvalue()
            db.close()
            raw = sqlite3.connect(home / "ponos.db")
            raw.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
            raw.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert _doctor_database() == 1
            assert "newer version" in out.getvalue()
        finally:
            db.close()


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _migrated_by_a_branch(location):
    """A file migrated by a branch whose last two migrations were in the other
    order — `_write_ups` before `_stops_have_a_cause`, as on 12/10/2026. Those
    that main has after them since, the branch did not have yet."""
    names = [db.name(migration) for migration in db.MIGRATIONS]
    first, second = names.index("stops_have_a_cause"), names.index("write_ups")
    assert second == first + 1, "the two this test swaps"
    branch = (*db.MIGRATIONS[:first], db.MIGRATIONS[second])
    db.open_at(location, branch).close()


@case
def a_database_migrated_by_a_branch_in_another_order_is_finished_by_main():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    _migrated_by_a_branch(location)
    connection = db.open_at(location)
    try:
        assert db.version(connection) == len(db.MIGRATIONS)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"write_ups", "mends", "history", "runs", "migrations"} <= tables, tables
        assert "code" in _columns(connection, "history") and "code" in _columns(connection, "runs")
        done = db.applied(connection)
        assert sorted(done) == sorted(db.name(migration) for migration in db.MIGRATIONS), done
        first = done.index("write_ups")
        assert done[first:first + 2] == ["write_ups", "stops_have_a_cause"], "the one applied under another rank is not again"
    finally:
        connection.close()
    again = db.open_at(location)
    try:
        assert db.version(again) == len(db.MIGRATIONS), "nothing left, nothing replayed"
    finally:
        again.close()


@case
def a_database_from_before_the_names_is_given_them_by_its_version():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    old = db.open_at(location, db.MIGRATIONS[:5])
    old.execute("DROP TABLE migrations")
    old.close()
    connection = db.open_at(location)
    try:
        names = [db.name(migration) for migration in db.MIGRATIONS]
        assert db.applied(connection) == names
        rows = connection.execute("SELECT name, at FROM migrations ORDER BY rowid").fetchall()
        assert all(at == "" for _, at in rows[:5]), "filled in: nobody wrote the moment down"
        assert all(at for _, at in rows[5:]), "applied now, and said when"
        assert db.disorder(connection) == ""
    finally:
        connection.close()


@case
def a_database_that_went_through_a_migration_this_code_does_not_know_is_refused_untouched():
    location = Path(tempfile.mkdtemp()) / "ponos.db"

    def notes(connection):
        connection.execute("CREATE TABLE notes (text TEXT)")

    # Another branch's: in the middle of the list, at the rank main has one more.
    db.open_at(location, (*db.MIGRATIONS[:-1], notes)).close()
    raw = sqlite3.connect(location)
    before = raw.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
    raw.close()
    try:
        db.open_at(location)
    except db.TooNew as error:
        assert "notes" in str(error) and "ponos update" in str(error), str(error)
    else:
        raise AssertionError("a migration nobody here knows must stop the file being written")
    raw = sqlite3.connect(location)
    try:
        assert raw.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall() == before
        assert raw.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    finally:
        raw.close()


@case
def doctor_says_when_the_migrations_are_not_in_the_codes_order():
    from ponos.__main__ import _doctor_database

    with _state_home() as home:
        try:
            _migrated_by_a_branch(home / "ponos.db")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert _doctor_database() == 0, "every table is there: a yellow line, not a red one"
            said = out.getvalue()
            assert "another order" in said and "stops_have_a_cause" in said, said
        finally:
            db.close()


@case
def a_checkout_does_not_write_the_real_state_unless_told_to():
    if C.checkout() is None:
        return  # a copy without its .git: an installation, which this is not about
    assert C.checkout() == ROOT
    previous = os.environ.pop("XDG_STATE_HOME", None)
    try:
        try:
            C.refuse_real_state()
        except C.RealStateRefused as error:
            assert "XDG_STATE_HOME" in str(error), str(error)
        else:
            raise AssertionError("a checkout without XDG_STATE_HOME must be refused")
        try:
            db.connect()
        except db.DatabaseError as error:
            assert "XDG_STATE_HOME" in str(error), str(error)
        else:
            raise AssertionError("nor open the real database")
    finally:
        if previous is not None:
            os.environ["XDG_STATE_HOME"] = previous
    home = Path(tempfile.mkdtemp())
    environment = {key: value for key, value in os.environ.items() if key != "XDG_STATE_HOME"}
    environment.update(HOME=str(home), PYTHONPATH=str(ROOT / "src"))
    done = subprocess.run([sys.executable, "-m", "ponos", "history"], env=environment,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "XDG_STATE_HOME=$(mktemp -d)" in done.stderr, done.stderr
    assert not (home / ".local" / "state").exists(), "nothing written"
    with _state_home():
        C.refuse_real_state()


# -- the run journal ---------------------------------------------------------


def _said_event(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _tool_event(name: str, payload: dict) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": payload}]}}


@case
def a_file_at_schema_version_one_gets_the_tool_and_cost_columns_and_keeps_its_steps():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    old = db.open_at(location, db.MIGRATIONS[:1])
    old.execute("INSERT INTO runs (ticket, started_at) VALUES ('t', 'now')")
    old.execute("INSERT INTO steps (run, position, at, kind, text) VALUES (1, 1, 'now', 'said', 'kept')")
    old.close()
    upgraded = db.open_at(location)
    try:
        assert db.version(upgraded) == len(db.MIGRATIONS) >= 2
        assert upgraded.execute("SELECT kind, text, tool, cost_usd FROM steps").fetchall() == [
            ("said", "kept", "", None)
        ]
    finally:
        upgraded.close()


@case
def a_model_is_said_as_provider_slash_model_wherever_it_is_shown():
    from ponos import models

    said = {
        "opus": "claude/opus",
        "Sonnet": "claude/sonnet",
        "haiku": "claude/haiku",
        "opus[1m]": "claude/opus",
        "claude-opus-4-1-20250805": "claude/opus",
        "claude-sonnet-4-5-20250929": "claude/sonnet",
        "claude-3-5-haiku-20241022": "claude/haiku",
        "claude-fable-5-1": "claude/fable",
        "deepseek-reasoner": "deepseek/r1",
        "deepseek-r1": "deepseek/r1",
        "DeepSeek-R1-0528": "deepseek/r1",
        "deepseek-chat": "deepseek/v3",
        "openrouter/auto": "openrouter/auto",
        "deepseek/deepseek-r1": "deepseek/deepseek-r1",
        "anthropic/claude-opus-4": "anthropic/claude-opus-4",
        "gpt-9": "gpt-9",
        "": "",
        "  ": "",
    }
    for given, expected in said.items():
        assert models.label(given) == expected, (given, models.label(given))


@case
def the_model_of_a_ticket_is_the_sessions_word_then_the_column_then_the_defaults():
    from ponos import models

    settings = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json"
    before = os.environ.pop("ANTHROPIC_MODEL", None)
    try:
        settings.unlink(missing_ok=True)
        # Nothing says: honest, not invented.
        assert models.describe("") == {"label": "", "full": "", "default": True}
        # Claude Code's own setting, when it has one.
        settings.write_text('{"model": "opus"}', encoding="utf-8")
        assert models.describe("") == {"label": "claude/opus", "full": "opus", "default": True}
        # The runner's configuration comes first.
        assert models.describe("", configured="sonnet")["label"] == "claude/sonnet"
        # The session's own word beats the rest, and the default stays said.
        found = models.describe("", "claude-haiku-4-5-20251001", "sonnet")
        assert found == {"label": "claude/haiku", "full": "claude-haiku-4-5-20251001", "default": True}
        # A column chosen is not a default.
        assert models.describe("haiku", configured="opus") == {
            "label": "claude/haiku", "full": "haiku", "default": False,
        }
        # A settings file that is not JSON is nobody knowing.
        settings.write_text("not json", encoding="utf-8")
        assert models.claude_default() == ""
    finally:
        settings.unlink(missing_ok=True)
        if before is not None:
            os.environ["ANTHROPIC_MODEL"] = before


@case
def a_run_keeps_the_model_its_session_announced():
    with _state_home():
        try:
            run = journal.Run.start(ticket="d" * 32, model="opus")
            run.event({"type": "system", "subtype": "init", "model": "claude-opus-4-1-20250805"})
            (found,) = journal.runs("d" * 32)
            assert (found["model"], found["reported"]) == ("opus", "claude-opus-4-1-20250805")
        finally:
            db.close()


@case
def a_run_is_written_step_by_step_and_closed_on_what_the_ticket_came_to():
    with _state_home():
        try:
            ticket = "3ed45168-0af4-8134-a677-f7f1e9024ae5"
            run = journal.Run.start(ticket=ticket, title="Journal", project="Ponos", session="s1", log="/x/a.jsonl")
            assert run.open
            run.event({"type": "system", "subtype": "init"})
            run.event(_said_event("I read the brief."))
            run.event(_tool_event("Bash", {"command": "python3 tests/run.py"}))
            run.event({"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": True, "content": "exit 1"}
            ]}})
            run.event({"type": "result", "total_cost_usd": 0.25})
            run.again("s2", "/x/a-again.jsonl")
            run.event(_tool_event("Read", {"file_path": "/repo/a.py"}))
            run.event({"type": "result", "total_cost_usd": 0.5})

            (found,) = journal.runs("e9024ae5")
            assert found["ticket"] == ticket.replace("-", "")
            assert found["status"] is None and found["ended_at"] is None, "still going"
            assert found["session"] == "s2" and found["log"] == "a-again.jsonl"
            assert found["cost_usd"] == 0.75 and found["steps"] == 4
            assert journal.runs(f"https://app.notion.com/p/Journal-{ticket.replace('-', '')}") == [found]

            run.end("done", "https://github.com/o/r/pull/1")
            run.end("failed", "too late: a run is closed once")
            (closed,) = journal.runs(ticket)
            assert closed["status"] == "done" and closed["reason"] == "https://github.com/o/r/pull/1"
            assert closed["ended_at"]

            steps = journal.steps(closed["id"])["steps"]
            assert [(step["kind"], step["label"], step["detail"], step["said"]) for step in steps] == [
                ("said", "I read the brief.", "", True),
                ("tool", "Bash", "python3 tests/run.py", False),
                ("error", "Error", "exit 1", False),
                ("tool", "Read", "/repo/a.py", False),
            ], steps
            assert [step["position"] for step in steps] == [1, 2, 3, 4]
            assert "cost_usd" not in steps[0] and steps[3]["cost_usd"] == 0.25, "the cost known then"
        finally:
            db.close()


@case
def a_run_is_read_a_page_at_a_time_from_its_end():
    with _state_home():
        try:
            run = journal.Run.start(ticket="a" * 32)
            for index in range(1, 451):
                run.event(_tool_event("Read", {"file_path": f"/f{index}"}))
            last = journal.steps(run.id)
            assert last["count"] == 450 and last["more"]
            assert [step["position"] for step in last["steps"]] == list(range(251, 451))
            before = journal.steps(run.id, before=251)
            assert [step["position"] for step in before["steps"]] == list(range(51, 251)) and before["more"]
            first = journal.steps(run.id, before=51)
            assert [step["position"] for step in first["steps"]] == list(range(1, 51)) and not first["more"]
            after = journal.steps(run.id, after=440)
            assert [step["position"] for step in after["steps"]] == list(range(441, 451))
            assert journal.steps(run.id, after=450)["steps"] == []
        finally:
            db.close()


@case
def a_journal_that_cannot_be_written_never_stops_a_ticket():
    with _state_home() as home:
        home.mkdir(parents=True, exist_ok=True)
        (home / "ponos.db").write_bytes(b"this is not a database" * 100)
        said: list[str] = []
        try:
            run = journal.Run.start(ticket="a" * 32, say=said.append)
            assert not run.open
            run.event(_said_event("nothing to write it into"))
            run.end("done")
            assert len(said) == 1 and "run journal off" in said[0], said
        finally:
            db.close()


@case
def every_road_out_of_a_ticket_closes_its_run():
    from ponos.execution import _both

    with _state_home():
        try:
            runner = Runner.__new__(Runner)
            runner._journals = {}
            ticket = ticket_module.Ticket(notion.Page(id="b" * 32, url="", title="t"))
            runner._journals[ticket.id] = journal.Run.start(ticket=ticket.id)
            result = {"ticket": "t", "id": ticket.id, "status": "blocked", "reason": "which header?"}
            assert runner._guarded(ticket, lambda: result) is result
            (closed,) = journal.runs(ticket.id)
            assert (closed["status"], closed["reason"]) == ("blocked", "which header?")
            assert not runner._journals, "closed once, and forgotten"
            # A ticket's work that ran no session has no run to close.
            assert runner._guarded(ticket, lambda: None) is None
        finally:
            db.close()

    heard: list[dict] = []

    def broken(event: dict) -> None:
        raise RuntimeError("Notion is down")

    listen = _both(heard.append, broken)
    with contextlib.redirect_stdout(io.StringIO()):
        listen({"n": 1})
        listen({"n": 2})
    assert heard == [{"n": 1}, {"n": 2}], "the page failing does not cost the journal its steps"


@case
def the_console_reads_a_tickets_runs_and_their_steps_from_the_journal():
    with _state_home():
        try:
            api = web_api.Api.__new__(web_api.Api)
            older = journal.Run.start(ticket="c" * 32, title="first")
            older.event(_said_event("one"))
            older.end("failed", "crashed")
            newer = journal.Run.start(ticket="c" * 32, title="second")
            newer.event(_tool_event("Bash", {"command": "ls"}))
            runs = api.runs("c" * 32)["runs"]
            assert [run["title"] for run in runs] == ["second", "first"]
            page = api.run_steps(newer.id)
            assert page["ended"] is False and page["count"] == 1
            assert page["steps"][0]["label"] == "Bash" and page["steps"][0]["detail"] == "ls"
            assert api.run_steps(older.id)["ended"] is True
            try:
                api.run_steps(999)
            except LookupError:
                pass
            else:
                raise AssertionError("an unknown run is a 404")
        finally:
            db.close()


@case
def ponos_logs_lists_a_tickets_runs_from_the_journal():
    with _state_home():
        try:
            run = journal.Run.start(ticket="d" * 32, title="A ticket", log=state.logs_dir() / "x-dddddddd.jsonl")
            run.event(_said_event("hello"))
            run.event({"type": "result", "total_cost_usd": 1.5})
            run.end("blocked", "which header?")
            (state.logs_dir() / "x-dddddddd.jsonl").write_text("", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert cli_main(["logs", "dddddddd", "--runs"]) == 0
            text = out.getvalue()
            assert "blocked" in text and "A ticket" in text and "1 steps" in text and "$1.50" in text, text
            assert "which header?" in text and "x-dddddddd.jsonl" in text, text
        finally:
            db.close()


# -- the MCP server ----------------------------------------------------------


def _mcp_call(api, grant, name: str, **arguments) -> dict:
    from ponos.web import mcp as web_mcp

    answer = web_mcp.handle(
        api, grant,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    )
    return answer["result"]


@case
def an_mcp_client_lists_what_waits_creates_a_task_and_answers_a_question():
    """The three gestures the connector exists for, on a board made of files.

    Nothing in what comes back names a page, a database or a property: a task,
    a project, a status. A task created goes through `create_ticket`, an answer
    is the comment the console's discussion writes, under the question — and
    every write is in the journal, with its client.
    """
    from ponos.web import mcp as web_mcp
    from ponos.web import oauth as web_oauth

    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        settings = C.Notion()
        blocked = board.create_row("tickets", "Choisir l'hébergeur", {"Status": settings.state("blocked")})
        board.update("tickets", blocked, {"Project": [project]})
        board.comment(blocked, f"{voice.MARKS['blocked']} Bloqué.\nQuestion : Dokploy ou Vercel ?")
        board.create_row("tickets", "Autre chose", {"Status": settings.state("ready")})
        api = _ideas_api(board)
        grant = web_oauth.Grant(client="c-1", name="claude.ai", scopes=frozenset({"read", "write"}))

        projects = _mcp_call(api, grant, "list_projects")["structuredContent"]["projects"]
        assert [(item["name"], item["repository"]) for item in projects] == [("Usine", "user/usine")]

        waiting = _mcp_call(api, grant, "list_tasks", waiting_for_you=True)["structuredContent"]
        assert [task["title"] for task in waiting["tasks"]] == ["Choisir l'hébergeur"]
        task = waiting["tasks"][0]
        assert task["project"] == "Usine" and task["status"] == "blocked" and task["waiting_for_you"]
        assert "url" not in task, "a task is not a Notion page"

        detail = _mcp_call(api, grant, "get_task", task=task["short"])["structuredContent"]
        assert "Dokploy ou Vercel" in detail["question"]
        assert detail["conversation"][-1]["from"] == "ponos"

        created = _mcp_call(
            api, grant, "create_task", title="Brancher le domaine", description="Sur Dokploy.",
            project="usine", type="code", priority=80,
        )
        assert not created["isError"], created
        made = board.page(created["structuredContent"]["id"])
        assert made.title == "Brancher le domaine"
        assert store.read(made, "Project") == [project]
        assert not store.read(made, "Status"), "a draft unless ready is asked for"
        assert "Sur Dokploy." in board.blocks_text(made.id)

        unknown = _mcp_call(api, grant, "create_task", title="X", project="Nulle part")
        assert unknown["isError"] and "Usine" in unknown["content"][0]["text"]

        refused = _mcp_call(api, grant, "answer_question", task=created["structuredContent"]["id"], answer="oui")
        assert refused["isError"], "only a blocked task is answered"

        answered = _mcp_call(api, grant, "answer_question", task=task["id"], answer="Dokploy", ready=True)
        assert not answered["isError"], answered
        said = board.comments(blocked)[-1].text
        assert said.endswith("Dokploy") and said != "Dokploy", "relayed, as the console's answer is"
        assert api.outbox.marks()[task["id"]].column == "ready"

        journal_lines = web_mcp.calls()
        assert [line["tool"] for line in journal_lines] == [
            "answer_question", "answer_question", "create_task", "create_task",
        ]
        assert journal_lines[0]["outcome"] == "ok" and journal_lines[0]["name"] == "claude.ai"
        assert journal_lines[1]["outcome"].startswith("refused")
        assert all(line["client"] == "c-1" and line["at"] for line in journal_lines)


# -- deciding on a card that waits on you -------------------------------------


@case
def a_blocked_session_names_what_it_stopped_on_and_a_finished_one_what_to_check():
    """CATEGORY and CAVEAT, read like the other fields: from the end, before RESULT."""
    from ponos import question

    asked = question.parse(
        "I tried.\nDONE: nothing\nWHY: no Cloudflare token\nCATEGORY: Access\n"
        "QUESTION: Which token?\nMODE: free\nRESULT: blocked — no token"
    )
    assert asked.category == "access" and asked.why == "no Cloudflare token"
    unknown = question.parse("WHY: x\nCATEGORY: weather\nQUESTION: Now?\nRESULT: blocked — x")
    assert unknown.category == "", "a category nobody offered is no category"
    assert question.caveats(
        "CAVEAT: quoted earlier\nDone.\nCAVEAT: not tried on Safari\n- CAVEAT: **no screenshot**\n"
        "RESULT: ok — the header"
    ) == ["not tried on Safari", "no screenshot"]
    assert question.caveats("Done.\nRESULT: ok — the header") == []
    assert "CATEGORY: <one word" in prompt.ASKING and "CAVEAT: <" in prompt.ASKING
    assert all("{asking}" in template for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.RESOLVE))


@case
def a_blocked_report_says_its_category_and_the_console_reads_it_back():
    """Written in front of why, in the runner's language, and read back in either."""
    from ponos import decisions, question

    for language, named in (("fr", "Accès manquant : "), ("en", "Missing access: ")):
        said = voice.Voice(language)
        asked = question.Question(
            ask="Which token?", mode="choice", options=["Production", "A new one"],
            done="branch ready", why="no Cloudflare token", category="access",
        )
        report = said.paragraphs(
            said.report(said.verdict("blocked", asked.done), *said.question(asked)), "Worktree kept."
        )
        assert named + "no Cloudflare token" in report
        assert question.found(report).options == ["Production", "A new one"], "the layout still reads"
        found = decisions.blockage(["an answer", report, "a reply of yours"])
        assert found.category == "access" and found.declared and found.reported
        assert found.reason == "no Cloudflare token" and found.done == "branch ready"
        assert found.detail == "Worktree kept." and found.question.ask == "Which token?"
        keys = [solution.key for solution in decisions.unblocking(found)]
        assert keys == ["option", "option", "done-retry", "instruct", "abandon", "other"], keys


@case
def a_ticket_blocked_before_the_categories_still_reads_as_a_reason_and_offers_defaults():
    """No name in front: the words give the kind away, and the defaults follow."""
    from ponos import decisions

    said = voice.Voice("fr")
    old = decisions.blockage(["🙋 Question\nWhich header, the dashboard's or the site's?"])
    assert old.category == "question" and not old.declared and old.reported
    assert old.reason == "Which header, the dashboard's or the site's?"
    offered = decisions.unblocking(old)
    assert [solution.key for solution in offered] == ["answer", "instruct", "abandon", "other"]
    assert len(offered) - 1 >= 2, "at least two solutions beside the free one"
    for key, category in (
        ("conflict-open", "conflict"), ("checks-red", "ci"), ("rebased-too-often", "conflict"),
    ):
        reason = said.sentence(said.say(key, base="main", branch="b", limit="5 $"))
        found = decisions.blockage([said.report(said.verdict("blocked"), reason)])
        assert found.category == category, (key, found)
        assert found.reason == reason
    budget = said.say("over-ticket-budget", limit="5,00 $")
    assert decisions.classify(budget) == "credits"
    assert decisions.classify("I need the SSH password of the server") == "access"
    assert decisions.classify("Il faut que tu installes Tailscale sur ta machine") == "manual"
    assert decisions.classify("too big for one ticket, split it") == "split"
    assert decisions.classify("Nothing to say") == "other"
    aside = decisions.blockage(["✅ To review — PR #3\nDone."])
    assert aside.category == "other" and not aside.reported, "set aside by hand: nothing said"
    assert [solution.key for solution in decisions.unblocking(aside, models=False)] == [
        "retry", "instruct", "abandon", "other",
    ]
    for category in decisions.DEFAULTS:
        offered = decisions.unblocking(decisions.Blockage(category=category))
        assert offered[-1].key == "other" and len(offered) >= 3, category


@case
def a_ticket_too_big_offers_its_sub_tickets_as_a_split():
    from ponos import decisions, question

    found = decisions.Blockage(
        category="split",
        question=question.Question(ask="Split?", mode="choice", options=["The API", "The page"]),
    )
    offered = decisions.unblocking(found)
    assert [solution.key for solution in offered] == ["split", "instruct", "abandon", "other"]
    assert offered[0].text == "The API\nThe page" and offered[0].column == "done"


@case
def a_question_that_proposes_to_close_the_ticket_offers_to_close_it_at_once():
    """A duplicate, nothing to do: "yes, close it" files it as done, no session to say so."""
    from ponos import decisions, question

    said = voice.Voice("fr")
    for ask in ("C'est un doublon de #12 : je le clos ?", "Nothing to do here — close it?"):
        found = decisions.Blockage(category="question", question=question.Question(ask=ask, mode="yes-no"))
        offered = decisions.unblocking(found)
        assert [solution.key for solution in offered][:3] == ["yes", "close", "answer"], ask
        assert offered[1].column == "done" and offered[1].needs == ""
    told = decisions.told(said, decisions.Solution("close", "done"))
    assert told == ["Décision : oui, clos-le — passé en terminé.", said.say("told-close")]
    work = decisions.Blockage(question=question.Question(ask="Which header?", mode="choice", options=["A", "B"]))
    assert "close" not in [solution.key for solution in decisions.unblocking(work)]
    free = decisions.Blockage(question=question.Question(ask="Close which one?", mode="free"))
    assert "close" not in [solution.key for solution in decisions.unblocking(free)], "a free answer is words"


@case
def a_review_report_carries_what_to_check_and_the_panel_offers_to_send_it_back():
    from ponos import decisions

    said = voice.Voice("fr")
    report = said.report(
        said.verdict("review", "PR #3", "2 commits"),
        "Ajoute un bouton.",
        "https://github.com/a/b/pull/3",
        *said.caveats(["Pas de test e2e", "Les captures restent à faire", "Le wording est à relire"]),
    )
    assert "À vérifier : Pas de test e2e" in report
    found = decisions.delivered([report])
    assert found.summary == "Ajoute un bouton." and found.pull_request.endswith("/pull/3")
    assert found.caveats == ["Pas de test e2e", "Les captures restent à faire", "Le wording est à relire"]
    assert found.facts == "PR #3 · 2 commits"
    offered = decisions.deciding(found, said, checks="failed")
    assert [solution.key for solution in offered] == [
        "validate", "rework", "fix-ci", "add-tests", "screenshots", "caveat", "reject",
    ]
    assert offered[0].column == "validated" and offered[-1].column == "done"
    assert "Le wording est à relire" in offered[5].text and offered[5].number == 3
    green = decisions.deciding(found, said, checks="passed", validate=False)
    assert green[0].column == "done" and "fix-ci" not in [solution.key for solution in green]
    assert decisions.checks_state([{"bucket": "pass"}, {"bucket": "fail"}]) == "failed"
    assert decisions.checks_state([{"bucket": "pass"}, {"bucket": "pending"}]) == "pending"
    assert decisions.checks_state([{"bucket": "pass"}, {"bucket": "skipping"}]) == "passed"
    assert decisions.checks_state([]) == "none"


@case
def each_choice_moves_the_ticket_and_leaves_the_instruction_for_the_next_session():
    """The panel's gestures, on a board of files: the comment, then the move.

    A choice that sends the ticket back to work writes the instruction first —
    as an answer relayed from the console, which the next session reads as the
    author's — and queues the move; one that files it away moves it at once,
    then says so, so that the runner never reads that comment as an answer.
    """
    settings = C.Notion()
    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        api = _ideas_api(board)
        said = api.runner.voice
        assert said.language == "en"
        asked = said.report(
            said.verdict("blocked", "nothing"),
            *said.question(type("Q", (), {"ask": "Which host?", "mode": "choice", "why": "",
                                          "options": ["Dokploy", "Vercel"], "category": ""})()),
        )

        def blocked(title: str, report: str = asked) -> str:
            page = board.create_row("tickets", title, {"Status": settings.state("blocked")})
            board.update("tickets", page, {"Project": [project]})
            board.comment(page, report)
            return page

        first = blocked("Choose the host")
        shown = api.decision(first)
        assert shown["column"] == "blocked" and shown["category"] == "question"
        assert [solution["key"] for solution in shown["solutions"]][:2] == ["option", "option"]
        assert shown["solutions"][1]["label"] == "option 2, “Vercel”"
        assert shown["solutions"][-1]["key"] == "other"

        done = api.decide(first, "option", number=2)
        assert done["column"] == "ready" and api.outbox.marks()[first].column == "ready"
        comment = board.comments(first)[-1].text
        assert comment.splitlines() == [
            "Answered from the console.", "Decision: option 2, “Vercel”.", "Option 2: Vercel.",
        ]
        assert conversation.is_relayed(comment), "read by the next session as the author's word"

        second = blocked("Install Tailscale")
        try:
            api.decide(second, "other")
        except ValueError:
            pass
        else:
            raise AssertionError("an instruction of your own needs its words")
        api.decide(second, "other", text="Use the auth key in 1Password.\nThen carry on.")
        assert board.comments(second)[-1].text.endswith("Use the auth key in 1Password.\nThen carry on.")

        third = blocked("Give up")
        api.decide(third, "abandon", text="Not needed any more.")
        # Given up on, not done: the board offers a cancelled column.
        assert store.read(board.page(third), "Status") == settings.state("cancelled"), "moved at once"
        assert third not in api.outbox.marks()
        assert board.comments(third)[-1].text.splitlines()[1:] == [
            "Decision: abandoned, moved to cancelled.", "Not needed any more.",
        ]

        fourth = blocked("Too big", said.report(
            said.verdict("blocked"),
            *said.question(type("Q", (), {"ask": "Split it?", "mode": "choice", "why": "two things",
                                          "options": ["The API", "The page"], "category": "split"})()),
        ))
        assert api.decision(fourth)["solutions"][0] == {
            "key": "split", "column": "done", "needs": "titles", "text": "The API\nThe page",
            "number": 0, "label": "split into sub-tickets",
        }
        api.decide(fourth, "split", titles=["The API", " ", "The page"])
        assert store.read(board.page(fourth), "Status") == settings.state("done")
        made = [page for page in board.query("tickets", {}) if page.title in ("The API", "The page")]
        assert len(made) == 2 and all(store.read(page, "Project") == [project] for page in made)
        assert all(not store.read(page, "Status") for page in made), "drafts, never a paid session"
        assert "split into 2 tickets: The API · The page" in board.comments(fourth)[-1].text

        fifth = blocked("Crashed twice", said.report(said.verdict("blocked"), "It went round in circles."))
        assert "model" in [solution["key"] for solution in api.decision(fifth)["solutions"]]
        api.decide(fifth, "model", model="opus")
        assert store.read(board.page(fifth), settings.prop("model")) == "opus"
        assert api.outbox.marks()[fifth].column == "ready"
        assert "Decision: run it again on opus." in board.comments(fifth)[-1].text

        reviewed = board.create_row("tickets", "A button", {"Status": settings.state("review")})
        board.comment(reviewed, said.report(
            said.verdict("review", "PR #3"), "Adds a button.", "https://github.com/a/b/pull/3",
            *said.caveats(["no screenshot taken"]),
        ))
        panel = api.decision(reviewed)
        assert panel["summary"] == "Adds a button." and panel["caveats"] == ["no screenshot taken"]
        assert panel["pull_request"] == "https://github.com/a/b/pull/3"
        assert [solution["key"] for solution in panel["solutions"]][-1] == "reject"
        api.decide(reviewed, "screenshots", text="Take them on mobile too.")
        assert api.outbox.marks()[reviewed].column == "ready"
        assert board.comments(reviewed)[-1].text.splitlines()[1:] == [
            "Decision: back to work: take the screenshots.", "Take them on mobile too.",
        ]

        ready = board.create_row("tickets", "Elsewhere", {"Status": settings.state("ready")})
        try:
            api.decision(ready)
        except ValueError:
            pass
        else:
            raise AssertionError("a ready ticket waits on nobody")


@case
def an_mcp_client_lists_the_solutions_of_a_blocked_task_and_applies_one():
    from ponos.web import oauth as web_oauth

    settings = C.Notion()
    with _state_home(), _board() as board:
        blocked = board.create_row("tickets", "Install Tailscale", {"Status": settings.state("blocked")})
        board.comment(blocked, f"{voice.MARKS['blocked']} Bloqué\nAction manuelle requise : il faut l'installer à la main\nC'est fait ?")
        api = _ideas_api(board)
        grant = web_oauth.Grant(client="c-1", name="claude.ai", scopes=frozenset({"read", "write"}))
        listed = _mcp_call(api, grant, "list_solutions", task=blocked)["structuredContent"]
        assert listed["category"] == "manual" and listed["declared"]
        assert listed["reason"] == "il faut l'installer à la main"
        assert listed["solutions"][0]["key"] == "answer"
        applied = _mcp_call(api, grant, "apply_solution", task=blocked, solution="done-retry")
        assert not applied["isError"], applied
        assert board.comments(blocked)[-1].text.startswith(("Répondu depuis MCP.", "Answered from MCP."))
        assert api.outbox.marks()[blocked].column == "ready"
        wrong = _mcp_call(api, grant, "apply_solution", task=blocked, solution="validate")
        assert wrong["isError"]


@case
def an_mcp_client_sorts_ideas_without_deleting_any():
    from ponos.web import oauth as web_oauth

    with _state_home(), _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        grant = web_oauth.Grant(client="c-1", name="Claude Code", scopes=frozenset({"read", "write"}))
        idea = _mcp_call(api, grant, "create_idea", title="Un mode sombre", project="Usine")["structuredContent"]
        assert idea["status"] == "proposed" and idea["kind"] == "ticket"
        assert _mcp_call(api, grant, "create_idea", title="Un club", project="Usine", kind="project")["isError"]
        sorted_one = _mcp_call(
            api, grant, "create_idea", title="Un audit des jetons", project="Usine", category="security"
        )["structuredContent"]
        assert sorted_one["category"] == "security" and idea["category"] == ""
        assert _mcp_call(api, grant, "create_idea", title="Un tag", project="Usine", category="marketing")["isError"]
        listed = _mcp_call(api, grant, "list_ideas", project="Usine")["structuredContent"]["ideas"]
        assert [item["title"] for item in listed] == ["Un mode sombre", "Un audit des jetons"]
        assert _mcp_call(api, grant, "list_ideas")["structuredContent"]["ideas"] == [], "the workspace's are apart"

        thrown = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="discard")["structuredContent"]
        assert thrown["status"] == "discarded"
        back = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="new")["structuredContent"]
        assert back["status"] == "proposed"
        kept = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="keep")["structuredContent"]
        assert kept["status"] == "kept" and not kept["task"], "keeping writes nothing on the board"
        made = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="ticket")["structuredContent"]
        assert made["status"] == "ticket" and made["task"]
        ticket = board.page(made["task"])
        assert ticket.title == "Un mode sombre" and store.read(ticket, "Project") == [project]


@case
def a_read_only_mcp_client_sees_and_can_call_no_tool_that_writes():
    from ponos.web import mcp as web_mcp
    from ponos.web import oauth as web_oauth

    with _state_home(), _board() as board:
        api = _ideas_api(board)
        reader = web_oauth.Grant(client="c-2", name="lecteur", scopes=frozenset({"read"}))
        listed = web_mcp.handle(api, reader, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {
        "whoami", "list_projects", "list_tasks", "get_task", "runner_status", "list_ideas",
        "list_solutions",
    }
        assert all(tool["annotations"]["readOnlyHint"] for tool in listed["result"]["tools"])
        me = _mcp_call(api, reader, "whoami")["structuredContent"]
        assert me["client"] == "lecteur" and me["access"] == "lecture seule", me
        refused = _mcp_call(api, reader, "create_task", title="Rien")
        assert refused["isError"] and "lecture" in refused["content"][0]["text"]
        assert api.board()["tickets"] == [], "nothing was written"
        assert web_mcp.calls()[0]["outcome"].startswith("refused"), "a refused write is journalled too"
        state.record({"id": "x", "status": "done", "project": "Usine", "cost_usd": 1.25})
        state.record({"id": "y", "status": "done", "cost_usd": 0.5})
        status = _mcp_call(api, reader, "runner_status", days=7)["structuredContent"]
        assert status["spend"]["period_usd"] == 1.75 and status["spend"]["today_usd"] == 1.75
        assert [item["project"] for item in status["spend"]["by_project"]] == ["Usine", "(sans projet)"]
        assert status["run_in_progress"] is False and status["sessions"] == []


@case
def no_mcp_tool_starts_a_run_runs_a_command_or_deletes_anything():
    """The whole list, written down: a tool added is a decision, not a drift."""
    from ponos.web import mcp as web_mcp

    names = [tool["name"] for tool in web_mcp.TOOLS]
    assert set(names) == set(web_mcp.HANDLERS)
    assert names == [
        "whoami", "list_projects", "list_tasks", "get_task", "runner_status", "list_ideas",
        "create_task", "answer_question", "list_solutions", "apply_solution", "create_idea",
        "set_idea_state",
    ]
    writes = [tool["name"] for tool in web_mcp.TOOLS if tool["scope"] == "write"]
    assert writes == ["create_task", "answer_question", "apply_solution", "create_idea", "set_idea_state"]
    status = next(tool for tool in web_mcp.TOOLS if tool["name"] == "create_task")
    assert status["inputSchema"]["properties"]["status"]["enum"] == ["draft", "ready"]
    for tool in web_mcp.TOOLS:
        assert len(tool["description"]) > 80, f"{tool['name']}: a description Claude can choose by"
        assert tool["title"] and len(tool["title"]) < 40, f"{tool['name']}: a title a person reads in a list"
    titles = [tool["title"] for tool in web_mcp.TOOLS]
    assert len(set(titles)) == len(titles), "two tools Claude would show under one name"


@case
def the_mcp_connector_says_its_name_and_who_holds_the_key():
    """What Claude shows once the address is pasted, and the first call to try.

    The icon is served from the site, never from the console: Claude fetches
    it without a key, and a console's files are behind its sign-in.
    """
    from ponos.web import mcp as web_mcp
    from ponos.web import oauth as web_oauth

    with _state_home(), _board() as board:
        board.create_row("projects", "Usine", {"Repository": "user/usine"})
        board.create_row("tickets", "Choisir l'hébergeur", {"Status": C.Notion().state("blocked")})
        api = _ideas_api(board)
        api._config.web.email = "moi@example.com"
        writer = web_oauth.Grant(client="c-1", name="claude.ai", scopes=frozenset({"read", "write"}))
        hello = web_mcp.handle(
            api, writer, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}
        )["result"]["serverInfo"]
        assert hello["name"] == "ponos" and hello["title"] == "Ponos" and hello["websiteUrl"] == "https://the-ponos.app"
        assert hello["description"] and all(icon["src"].startswith("https://the-ponos.app/") for icon in hello["icons"])
        answer = web_mcp.handle(
            api, writer,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}},
            "https://ponos.example",
        )["result"]
        me = answer["structuredContent"]
        assert not answer["isError"]
        assert me["console"] == "https://ponos.example" and me["email"] == "moi@example.com"
        assert me["client"] == "claude.ai" and me["access"] == "lecture et écriture"
        assert me["projects"] == 1 and me["waiting_for_you"] == 1 and me["board"] == api.config.storage.mode
        assert web_mcp.calls() == [], "reading who you are is no write"
        refused = _mcp_call(api, writer, "whoami", qui="moi")
        assert refused["isError"], "whoami takes no argument"


@case
def the_mcp_server_is_reached_through_oauth_with_pkce_and_its_own_keys():
    """Discovery, registration, consent, code, token, tools — over HTTP.

    The console's own token is not a key to `/mcp`; consent asks for it when
    the browser is signed out; write is granted only when ticked; a code is
    good once, and only with its verifier.
    """
    import base64
    import hashlib
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qs, urlencode, urlparse

    from ponos.web import oauth as web_oauth
    from ponos.web import server as web_server

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(Stay)

    with _state_home(), _board() as board:
        board.create_row("tickets", "Un ticket", {"Status": C.Notion().state("blocked")})
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"

        def ask(path, data=None, headers=None, method=None):
            request = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
            try:
                with opener.open(request, timeout=5) as response:
                    return response.status, dict(response.headers), response.read()
            except urllib.error.HTTPError as error:
                return error.code, dict(error.headers), error.read()

        def rpc(token, method, params=None):
            body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}}).encode()
            return ask("/mcp", body, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        try:
            code, headers, _ = rpc("tok", "tools/list")
            assert code == 401, "the console's token opens the console, not the MCP server"
            assert "resource_metadata=" in headers["WWW-Authenticate"]
            # Any first contact gets the 401 that makes Claude offer "Connect", as Leadz answers it.
            code, headers, _ = ask("/mcp")
            assert code == 401 and headers["WWW-Authenticate"] == (
                f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"'
            ), "a GET without a key: a 401, not a 405"
            resource = json.loads(ask("/.well-known/oauth-protected-resource/mcp")[2])
            assert resource["resource"] == f"{base}/mcp" and resource["scopes_supported"] == ["read", "write"]
            server = json.loads(ask("/.well-known/oauth-authorization-server")[2])
            assert server["code_challenge_methods_supported"] == ["S256"]

            code, _, body = ask("/oauth/register", json.dumps({"redirect_uris": ["http://evil.example/cb"]}).encode(),
                                {"Content-Type": "application/json"})
            assert code == 400, "a code is never sent in clear across a network"
            code, _, body = ask(
                "/oauth/register",
                json.dumps({"client_name": "claude.ai", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]}).encode(),
                {"Content-Type": "application/json"},
            )
            assert code == 201, body
            client_id = json.loads(body)["client_id"]

            verifier = "v" * 50
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            params = {
                "response_type": "code", "client_id": client_id,
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": challenge, "code_challenge_method": "S256",
                "scope": "read write", "state": "s-1",
            }
            code, _, page = ask("/oauth/authorize?" + urlencode(params))
            assert code == 200 and b"claude.ai" in page and b'name="token"' in page, "signed out: the token is asked"
            assert b'name="write"' in page

            code, _, _ = ask("/oauth/authorize", urlencode({**params, "decision": "allow", "token": "nope"}).encode(),
                             {"Content-Type": "application/x-www-form-urlencoded"})
            assert code == 401
            code, _, _ = ask("/oauth/authorize", urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                             {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://evil.example"})
            assert code == 403, "a consent posted from another page"

            # Write left unticked: read only.
            code, headers, _ = ask("/oauth/authorize", urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                                   {"Content-Type": "application/x-www-form-urlencoded", "Origin": base})
            assert code == 302, code
            back = urlparse(headers["Location"])
            assert back.netloc == "claude.ai"
            given = parse_qs(back.query)
            assert given["state"] == ["s-1"] and given["iss"] == [base]

            def exchange(**form):
                return ask("/oauth/token", urlencode(form).encode(), {"Content-Type": "application/x-www-form-urlencoded"})

            code, _, body = exchange(grant_type="authorization_code", code=given["code"][0], client_id=client_id,
                                     redirect_uri=params["redirect_uri"], code_verifier="w" * 50)
            assert code == 400 and json.loads(body)["error"] == "invalid_grant", "the wrong verifier"
            code, _, body = exchange(grant_type="authorization_code", code=given["code"][0], client_id=client_id,
                                     redirect_uri=params["redirect_uri"], code_verifier=verifier)
            assert code == 400, "a code refused once is spent"

            code, headers, _ = ask("/oauth/authorize", urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                                   {"Content-Type": "application/x-www-form-urlencoded", "Origin": base})
            fresh = parse_qs(urlparse(headers["Location"]).query)["code"][0]
            code, _, body = exchange(grant_type="authorization_code", code=fresh, client_id=client_id,
                                     redirect_uri=params["redirect_uri"], code_verifier=verifier)
            assert code == 200, body
            tokens = json.loads(body)
            assert tokens["scope"] == "read" and tokens["token_type"] == "Bearer"

            code, _, body = rpc(tokens["access_token"], "initialize", {"protocolVersion": "2025-06-18"})
            assert code == 200 and json.loads(body)["result"]["protocolVersion"] == "2025-06-18"
            code, _, _ = ask("/mcp", json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
                             {"Authorization": f"Bearer {tokens['access_token']}"})
            assert code == 202
            listed = json.loads(rpc(tokens["access_token"], "tools/list")[2])["result"]["tools"]
            assert "create_task" not in {tool["name"] for tool in listed}
            assert ask("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}"})[0] == 405, "no stream"
            # A client that names where it runs is not refused for it: the key is the lock.
            code, _, body = ask(
                "/mcp",
                json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "whoami"}}).encode(),
                {"Authorization": f"Bearer {tokens['access_token']}", "Content-Type": "application/json",
                 "Origin": "https://claude.ai"},
            )
            assert code == 200, code
            me = json.loads(body)["result"]["structuredContent"]
            assert me["console"] == base and me["client"] == "claude.ai" and me["access"] == "lecture seule"
            answer = json.loads(rpc(tokens["access_token"], "tools/call", {"name": "list_tasks", "arguments": {"waiting_for_you": True}})[2])
            assert [task["title"] for task in answer["result"]["structuredContent"]["tasks"]] == ["Un ticket"]
            answer = json.loads(rpc(tokens["access_token"], "tools/call", {"name": "create_task", "arguments": {"title": "Non"}})[2])
            assert answer["result"]["isError"], "read only cannot create"

            # A refresh turns over; the old one is spent.
            code, _, body = exchange(grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
            assert code == 200 and json.loads(body)["scope"] == "read"
            code, _, _ = exchange(grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
            assert code == 400

            # Write, ticked this time; then taken back.
            code, headers, _ = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "tok", "write": "1"}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded", "Origin": base},
            )
            writer = parse_qs(urlparse(headers["Location"]).query)["code"][0]
            code, _, body = exchange(grant_type="authorization_code", code=writer, client_id=client_id,
                                     redirect_uri=params["redirect_uri"], code_verifier=verifier)
            assert json.loads(body)["scope"] == "read write"
            written = json.loads(body)["access_token"]
            listed = json.loads(rpc(written, "tools/list")[2])["result"]["tools"]
            assert "create_task" in {tool["name"] for tool in listed}
            assert web_oauth.revoke(client_id) >= 2
            assert rpc(written, "tools/list")[0] == 401, "revoked"

            # Refused: no redirect to an address the client did not register.
            code, headers, _ = ask("/oauth/authorize?" + urlencode({**params, "redirect_uri": "https://evil.example/cb"}))
            assert code == 400 and "Location" not in headers
            code, headers, _ = ask("/oauth/authorize?" + urlencode({**params, "code_challenge_method": "plain"}))
            assert code == 302 and "error=invalid_request" in headers["Location"]
        finally:
            console.shutdown()
            console.server_close()


@case
def the_mcp_metadata_names_the_public_address_behind_a_proxy_that_says_nothing():
    """`web.url`, as Leadz's DEFAULT_URI: a tunnel adds no X-Forwarded-Proto.

    Without it the addresses claude.ai reads would all be `http://`, and it
    refuses them; with it, Claude Code on this machine still reads the
    loopback address it typed.
    """
    import urllib.request

    from ponos.web import server as web_server

    with _state_home(), _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        api._config.web.host = "0.0.0.0"  # a wider bind: the Host check is the token's then
        api._config.web.url = "https://ponos.example"
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]

        def metadata(host: str) -> dict:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp", headers={"Host": host}
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read())

        try:
            outside = metadata("abc.lhr.life")
            assert outside["resource"] == "https://ponos.example/mcp", outside
            assert outside["authorization_servers"] == ["https://ponos.example"]
            here = metadata(f"127.0.0.1:{port}")
            assert here["resource"] == f"http://127.0.0.1:{port}/mcp", here
        finally:
            console.shutdown()
            console.server_close()


@case
def a_loopback_console_answers_the_name_web_url_gives_it_and_no_other():
    """`tailscale serve` relays to 127.0.0.1 and keeps the tailnet name as Host.

    That name is the one `web.url` says, exactly: not any `*.ts.net`, which
    another page could point at this machine as well as it could any domain.
    """
    import urllib.error
    import urllib.request

    from ponos.web import server as web_server

    with _state_home(), _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]

        def status(host: str) -> int:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp", headers={"Host": host}
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code

        try:
            assert status("laptop.tail1234.ts.net") == 421, "no web.url: only this machine's names"
            assert status(f"127.0.0.1:{port}") == 200
            api._config.web.url = "https://laptop.tail1234.ts.net"
            assert status("laptop.tail1234.ts.net") == 200
            assert status("laptop.tail1234.ts.net:443") == 200
            assert status("other.tail1234.ts.net") == 421, "another machine of the same tailnet"
            assert status("evil.example") == 421
            assert status(f"127.0.0.1:{port}") == 200
        finally:
            console.shutdown()
            console.server_close()


@case
def a_local_mcp_token_is_drawn_once_and_kept_as_a_digest():
    from ponos.web import oauth as web_oauth

    with _state_home():
        identifier, token = web_oauth.local("Claude Code", write=False)
        grant = web_oauth.check(token)
        assert grant is not None and grant.scope == "read" and grant.name == "Claude Code"
        with db.transaction(immediate=False) as connection:
            stored = [row[0] for row in connection.execute("SELECT hash FROM mcp_tokens")]
        assert token not in stored and web_oauth.digest(token) in stored
        assert [client["scope"] for client in web_oauth.clients()] == ["read"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert cli_main(["mcp", "revoke", identifier]) == 0
        assert web_oauth.check(token) is None
        assert web_oauth.check("") is None



# -- why a ticket stopped -----------------------------------------------------


def _fail_calls() -> list[tuple[str, int, ast.Call]]:
    """Every `self._fail(...)` of the run's chapters, where it is written.

    The run's modules are the ones at the top of the package: `web/` and
    `channels/` have a `_fail` of their own, which answers an HTTP request.
    """
    found = []
    for path in sorted((ROOT / "src/ponos").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_fail"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                found.append((path.name, node.lineno, node))
    return found


@case
def every_fail_carries_a_code_the_catalogue_knows():
    """The guarantee the catalogue is for: no stop said without its cause.

    A literal code is checked against the catalogue as it is written; the one
    a session's ending decides (`_why_stopped`) is a variable at the call, and
    its literals are checked where they are written instead.
    """
    from ponos import blocks

    calls = _fail_calls()
    assert len(calls) >= 25, f"{len(calls)} calls to _fail — the scan missed the run's modules"
    for name, line, call in calls:
        given = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "code" in given, f"{name}:{line} — a _fail without code="
        code = given["code"]
        if isinstance(code, ast.Constant):
            assert code.value in blocks.CAUSES, f"{name}:{line} — {code.value!r} is not in blocks.py"
        else:
            assert isinstance(code, ast.Name), f"{name}:{line} — code= is neither a code nor a name"
    asked = []
    for path in sorted((ROOT / "src/ponos").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in (
                "_why_stopped",
                "_blocked_by",
            ):
                asked += [
                    constant.value
                    for argument in node.args
                    for constant in ast.walk(argument)
                    if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
                ]
    assert len(asked) >= 4, asked
    for code in asked:
        assert code in blocks.CAUSES, f"{code!r} is not in blocks.py"
    # And at run time: a code the catalogue does not hold is refused, not written.
    runner = _board_runner([_reviewed("p-1", "In progress", None)], {"blocked": "Blocked"})
    try:
        runner._fail(ticket_module.Ticket(runner.client._pages[0]), "x", code="merge.nope")
    except ValueError as error:
        assert "merge.nope" in str(error)
    else:
        raise AssertionError("an unknown code was accepted")
    assert runner.client.written == []


@case
def every_cause_is_described_whole_in_both_languages():
    from ponos import blocks

    assert blocks.UNKNOWN in blocks.CAUSES
    for given in (
        "worktree.residue", "worktree.interrupted", "session.killed", "session.not-started",
        "session.no-answer", "session.no-commit", "session.question", "merge.base-red",
        "merge.checks-failed", "merge.base-moving", "merge.refused", "merge.conflict-decision",
        "merge.push-refused", "merge.no-pr", "publish.failed", "notion.write-failed",
        "access.sudo", "access.credentials", "project.no-repo",
    ):
        assert given in blocks.CAUSES, f"the ticket's {given} is missing"
    for code, cause in blocks.CAUSES.items():
        assert code == blocks.UNKNOWN or re.fullmatch(r"[a-z]+\.[a-z-]+", code), code
        assert cause.family in blocks.FAMILIES, code
        assert cause.who in blocks.WHO, code
        assert cause.action in blocks.ACTIONS, code
        assert re.fullmatch(r"retry:\d|wait-base|ask", cause.policy), code
        for language in voice.LANGUAGES:
            assert cause.label[language].strip() and cause.help[language].strip(), code
            assert len(cause.label[language]) <= 32, f"{code}: a badge, not a sentence"
        for key in cause.said:
            assert key in voice._SAID, f"{code} names the voice key {key!r}, which does not exist"
    # The families are drawn by the console, one icon each: the same five.
    console = (FRONTEND / "src/components/console/ticket-bits.tsx").read_text(encoding="utf-8")
    for family in blocks.FAMILIES:
        assert f"{family}:" in console or f'"{family}":' in console, family


@case
def every_sentence_said_for_a_cause_is_read_back_to_it():
    """What the migration counts on: today's sentences, and those the history holds."""
    from ponos import blocks

    values = {
        "base": "main", "branch": "ticket/x", "limit": "$5", "origin": "Validated",
        "problem": "x", "url": "https://github.com/o/r/pull/1",
    }
    for code, cause in blocks.CAUSES.items():
        for key in cause.said:
            if code == "worktree.interrupted":
                continue  # asked as a question, never kept as a sentence
            for language in voice.LANGUAGES:
                sentence = voice.Voice(language).say(key, **values)
                assert blocks.classify(sentence) == code, (code, language, sentence)
    heard = {
        "its conflicts were resolved, but its checks fail": "merge.checks-failed",
        "ses conflits ont été résolus, mais ses vérifications échouent": "merge.checks-failed",
        "`dev` keeps moving faster than its pull request can be replayed onto it": "merge.base-moving",
        "`main` avance plus vite que sa pull request ne peut être rejouée dessus": "merge.base-moving",
        "the pull request could not be merged": "merge.refused",
        "la pull request n'a pas voulu fusionner": "merge.refused",
        "sa pull request est en conflit avec `main`, et le conflit demande une décision": "merge.conflict-decision",
        "it was validated, but there is no pull request to merge": "merge.no-pr",
        "commits made but the push was refused": "merge.push-refused",
        "worktree could not be created": "worktree.residue",
        "je n'ai pas pu créer le worktree pour travailler": "worktree.residue",
        "the session stopped to ask you something": "session.question",
        "la session s’est arrêtée pour poser une question": "session.question",
        "the agent stopped without deciding": "session.question",
        "the agent stopped without answering": "session.no-answer",
        "la session s'est arrêtée sans écrire de réponse": "session.no-answer",
        "the session declared itself done without a single commit": "session.no-commit",
        "the session failed": "session.killed",
        "la session n'est pas allée au bout": "session.killed",
        "Claude session could not be started": "session.not-started",
        "the Claude session would not start": "session.not-started",
        "something nobody ever wrote": "unknown",
        "": "unknown",
    }
    for sentence, code in heard.items():
        assert blocks.classify(sentence) == code, (sentence, blocks.classify(sentence), code)


@case
def a_stop_writes_its_cause_on_the_board_and_in_its_result_and_leaving_clears_it():
    runner = _board_runner(
        [_reviewed("p-stop", "In progress", None)], {"blocked": "Blocked", "failed": "Failed"}
    )
    ticket = ticket_module.Ticket(runner.client._pages[0])
    blocked = runner._fail(
        ticket, runner.voice.say("merge-refused"), code="merge.refused", blocked=True,
        question="?",
    )
    assert blocked["status"] == "blocked" and blocked["code"] == "merge.refused", blocked
    assert runner.client.written == [("p-stop", {"Status": "Blocked", "Blocage": "merge.refused"})]
    failed = runner._fail(ticket, runner.voice.say("crashed"), "boom", code="runner.crashed")
    assert failed["code"] == "runner.crashed", failed
    assert runner.client.written[-1] == ("p-stop", {"Status": "Failed", "Blocage": "runner.crashed"})

    # The page now says why it stopped; the next status that is not a stop empties it.
    page = runner.client._pages[0]
    page.properties["Blocage"] = {"type": "select", "select": {"name": "runner.crashed"}}
    page.properties["Status"] = {"type": "status", "status": {"name": "Failed"}}
    runner.client.written.clear()
    runner._set(ticket, Status="In progress", Runner="ponos@laptop")
    assert runner.client.written == [
        ("p-stop", {"Blocage": "", "Status": "In progress", "Runner": "ponos@laptop"})
    ], runner.client.written
    # A card with nothing in the column is not written to for nothing.
    del page.properties["Blocage"]
    runner.client.written.clear()
    runner._set(ticket, Status="Done")
    assert runner.client.written == [("p-stop", {"Status": "Done"})], runner.client.written


@case
def a_session_that_did_not_finish_is_told_by_its_cause():
    runner = _board_runner([_reviewed("p-1", "In progress", None)], {"blocked": "Blocked"})
    ended = session.Outcome(
        ok=False, blocked=True, session_id="s", summary="Which one?", log=Path("/tmp/x")
    )
    code, sentence, detail = runner._why_stopped(ended, "session.question")
    assert (code, detail) == ("session.question", "Which one?")
    assert sentence == runner.voice.say("asked-something")
    ended.over_budget = True
    code, sentence, _ = runner._why_stopped(ended, "session.question")
    assert code == "session.over-budget" and "$" in sentence, (code, sentence)


@case
def the_board_offers_the_column_and_doctor_names_it_when_it_is_missing():
    from ponos import blocks

    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    column = provision.tickets_schema(settings)["Blocage"]
    options = [option["name"] for option in column["select"]["options"]]
    assert options == list(blocks.CODES), options
    assert "block" in store.COLUMNS and store.COLUMNS["block"][0] == ("select",)
    assert files.schemas(settings)["tickets"]["Blocage"] == "select"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        from ponos.__main__ import _doctor_columns
        missing = _doctor_columns({"Status": "status"}, settings)
    assert "Blocage" in out.getvalue() and missing >= 1, out.getvalue()


@case
def the_history_written_before_the_codes_is_reclassed_by_its_sentence():
    """Migration 17, on a file migrated as far as 16: every stop gets its code."""
    with tempfile.TemporaryDirectory() as directory:
        location = Path(directory) / "ponos.db"
        before = db.open_at(location, db.MIGRATIONS[:16])
        lines = [
            {"id": "a", "status": "blocked", "reason": "the session stopped to ask you something"},
            {"id": "b", "status": "failed", "reason": "je n'ai pas pu créer le worktree pour travailler"},
            {"id": "c", "status": "blocked", "reason": "ses conflits ont été résolus, mais ses vérifications échouent"},
            {"id": "d", "status": "failed", "reason": "a sentence from nowhere"},
            {"id": "e", "status": "done", "reason": ""},
        ]
        for line in lines:
            before.execute(
                "INSERT INTO history (ticket, status, entry) VALUES (?, ?, ?)",
                (line["id"], line["status"], json.dumps(line)),
            )
        before.execute(
            "INSERT INTO runs (ticket, started_at, status, reason)"
            " VALUES ('a', '2026-10-01', 'blocked', 'the session called itself done without committing anything')"
        )
        before.commit()
        before.close()
        after = db.open_at(location)
        try:
            rows = after.execute("SELECT ticket, code, entry FROM history ORDER BY id").fetchall()
            assert [(ticket, code) for ticket, code, _ in rows] == [
                ("a", "session.question"),
                ("b", "worktree.residue"),
                ("c", "merge.checks-failed"),
                ("d", "unknown"),
                ("e", ""),
            ], rows
            assert json.loads(rows[1][2])["code"] == "worktree.residue"
            assert "code" not in json.loads(rows[4][2])
            assert after.execute("SELECT code FROM runs").fetchone() == ("session.no-commit",)
        finally:
            after.close()


@case
def a_stop_is_kept_with_its_code_in_the_history_and_the_run():
    with _state_home():
        state.record({"id": "t-1", "status": "blocked", "reason": "x", "code": "merge.refused"})
        state.record({"id": "t-2", "status": "done"})
        state.record({"id": "t-1", "status": "failed", "reason": "y", "code": "runner.crashed"})
        assert state.history(1)[0]["code"] == "runner.crashed"
        # Keyed as a card is: the page id without its dashes.
        assert state.causes() == {"t1": "runner.crashed"}
        run = journal.Run.start(ticket="3f745168" * 4, title="A ticket")
        run.end("blocked", "z", "session.question")
        assert journal.runs("3f745168" * 4)[0]["code"] == "session.question"


@case
def a_stopped_card_carries_its_cause_from_the_board_or_else_from_the_history():
    from ponos import blocks

    with _state_home():
        state.record({"id": "c2", "status": "failed", "reason": "x", "code": "merge.refused"})
        state.record({"id": "c4", "status": "blocked", "reason": "x", "code": "merge.refused"})
        cards = [
            {"id": "c1", "column": "blocked", "block": blocks.describe("session.question")},
            {"id": "c2", "column": "failed", "block": None},
            {"id": "c3", "column": "blocked", "block": None},
            # Left the stopped columns: whatever the column still said, it is not drawn.
            {"id": "c4", "column": "ready", "block": blocks.describe("merge.refused")},
        ]
        web_api._causes(cards)
        assert [(card["block"] or {}).get("code") for card in cards] == [
            "session.question", "merge.refused", None, None,
        ], cards
        said = cards[0]["block"]
        assert said["family"] == "question" and said["action"] == "answer"
        assert said["label"]["fr"] and said["help"]["en"]


@case
def the_statistics_count_the_stops_by_cause_and_by_week():
    from ponos.web import statistics as web_statistics

    history = [
        {"at": "2026-10-05T09:00:00+00:00", "status": "blocked", "code": "session.question"},
        {"at": "2026-10-06T09:00:00+00:00", "status": "failed", "code": "merge.checks-failed"},
        {"at": "2026-10-07T09:00:00+00:00", "status": "blocked", "code": "session.question"},
        # Written before the codes and never migrated: read back from its sentence.
        {"at": "2026-10-13T09:00:00+00:00", "status": "blocked", "reason": "the pull request would not merge"},
        {"at": "2026-10-13T09:00:00+00:00", "status": "done"},
        {"at": "2026-09-01T09:00:00+00:00", "status": "blocked", "code": "session.question"},
    ]
    found = web_statistics.figures(
        [], history, date(2026, 10, 1), date(2026, 10, 20), timezone.utc
    )["blocks"]
    assert found["total"] == 4, found
    assert [week["week"] for week in found["weeks"]] == [
        "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19",
    ], found["weeks"]
    assert found["weeks"][0]["counts"] == {}
    assert found["weeks"][1]["counts"] == {"session.question": 2, "merge.checks-failed": 1}
    assert found["weeks"][2]["counts"] == {"merge.refused": 1}
    assert [(cause["code"], cause["count"]) for cause in found["causes"]] == [
        ("session.question", 2), ("merge.checks-failed", 1), ("merge.refused", 1),
    ]
    assert found["causes"][0]["family"] == "question" and found["causes"][0]["label"]["fr"]


@case
def the_mcp_tab_reads_claude_mcp_list_without_its_keys_and_tests_the_401_a_live_server_gives():
    """`claude mcp list` is the source of the servers, and what it prints may hold a key.

    A URL keeps its host and path, a command its program; a server that wants
    signing in is neither ok nor failing. The test asks the way a client does,
    without a key, and each way the answer can be wrong is a code.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from ponos.web import mcp_setup

    listed = mcp_setup.parse(
        "Checking MCP server health...\n\n"
        "notion: https://mcp.notion.com/mcp?key=SECRET (HTTP) - ✓ Connected\n"
        "github: https://api.example.com/mcp - ⚠ Needs authentication\n"
        "local: npx -y @x/server --token=SECRET - ✗ Failed to connect\n"
    )
    assert [(one["name"], one["state"]) for one in listed] == [
        ("notion", "ok"), ("github", "auth"), ("local", "error")], listed
    assert listed[0]["target"] == "https://mcp.notion.com/mcp" and listed[2]["target"] == "npx", listed
    assert "SECRET" not in json.dumps(listed)

    answers = {"/mcp": 401, "/gone/mcp": 404, "/moved/mcp": 421}
    announced = {"resource": ""}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            status = answers.get(self.path, 404)
            self.send_response(status)
            if status == 401:
                self.send_header("WWW-Authenticate", f'Bearer resource_metadata="http://{self.headers["Host"]}/meta"')
            self.end_headers()

        def do_GET(self):
            body = json.dumps({"resource": announced["resource"] or f"http://{self.headers['Host']}/mcp"}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert mcp_setup.probe(f"{base}/mcp")["ok"] is True
        assert mcp_setup.probe(f"{base}/gone/mcp")["code"] == "not-found"
        assert mcp_setup.probe(f"{base}/moved/mcp")["code"] == "misrouted"
        announced["resource"] = "https://elsewhere.example/mcp"
        mismatch = mcp_setup.probe(f"{base}/mcp")
        assert mismatch["code"] == "address-mismatch" and mismatch["seen"] == announced["resource"], mismatch
    finally:
        server.shutdown()
        server.server_close()
    assert mcp_setup.probe("")["code"] == "no-address"
    assert mcp_setup.probe("http://127.0.0.1:1/mcp")["code"] == "unreachable"
    overview = mcp_setup.overview("http://127.0.0.1:8787", "https://p.example/")
    assert overview["local"] == "http://127.0.0.1:8787/mcp" and overview["public"] == "https://p.example/mcp"


def _span(start: str, end: str | None, status: str | None = "done", code: str = "", last: str = "") -> dict:
    day = "2026-10-14T"
    return {
        "start": day + start + "+00:00",
        "end": day + end + "+00:00" if end else None,
        "status": status,
        "code": code,
        "last": day + (last or end or start) + "+00:00",
    }


def _at(clock: str) -> datetime:
    return datetime.fromisoformat("2026-10-14T" + clock + "+00:00")


@case
def a_ticket_that_works_waits_for_an_answer_and_works_again_counts_only_the_work():
    """10 min, 30 min waiting on a question, 5 min more: the clock reads 15."""
    spans = [
        _span("10:00:00", "10:10:00", "blocked", "session.question"),
        _span("10:40:00", "10:45:00", "done"),
    ]
    one = worktime.measure(spans, "review", _at("12:00:00"))
    assert one == {"work": 900, "paused": 1800, "sessions": 2, "running": False, "pause": ""}, one


@case
def the_clock_runs_on_a_live_run_and_stops_on_a_blocked_one():
    live = [_span("10:00:00", None, None, last="10:04:30")]
    going = worktime.measure(live, "progress", _at("10:05:00"))
    assert going and going["running"] and going["work"] == 300 and going["pause"] == "", going
    # The same run, once the ticket is blocked on a question: the clock stops where it ended.
    stopped = [_span("10:00:00", "10:05:00", "blocked", "session.question")]
    waiting = worktime.measure(stopped, "blocked", _at("10:35:00"))
    assert waiting and not waiting["running"] and waiting["work"] == 300, waiting
    assert waiting["pause"] == "question" and waiting["paused"] == 1800, waiting
    assert worktime.measure(stopped, "blocked", _at("10:36:00"))["work"] == 300  # type: ignore[index]


@case
def review_and_the_wait_in_ready_are_nobodys_pause_and_credit_is_one():
    reviewed = worktime.measure([_span("10:00:00", "10:20:00", "done")], "review", _at("18:00:00"))
    assert reviewed and reviewed["work"] == 1200 and reviewed["paused"] == 0 and reviewed["pause"] == "", reviewed
    # A correction after review: the days in review are not counted either.
    again = worktime.measure(
        [_span("10:00:00", "10:20:00", "done"), _span("15:00:00", "15:10:00", "done")], "review", _at("18:00:00")
    )
    assert again and again["work"] == 1800 and again["paused"] == 0, again
    credit = worktime.measure([_span("10:00:00", "10:20:00", "waiting")], "ready", _at("11:20:00"))
    assert credit and credit["pause"] == "credit" and credit["paused"] == 3600, credit
    failed = worktime.measure([_span("10:00:00", "10:20:00", "failed", "runner.crashed")], "failed", _at("10:30:00"))
    assert failed and failed["pause"] == "blocked", failed


@case
def a_run_the_runner_never_closed_stops_at_its_last_step_and_an_overlap_counts_once():
    killed = worktime.measure([_span("10:00:00", None, None, last="10:07:00")], "ready", _at("20:00:00"))
    assert killed and killed["work"] == 420 and not killed["running"], killed
    # Still "progress" but silent for hours: the runner is gone, the clock is not running.
    silent = worktime.measure([_span("10:00:00", None, None, last="10:07:00")], "progress", _at("20:00:00"))
    assert silent and silent["work"] == 420 and not silent["running"], silent
    overlap = worktime.measure([_span("10:00:00", "10:10:00"), _span("10:05:00", "10:20:00")], "review", _at("11:00:00"))
    assert overlap and overlap["work"] == 1200, overlap
    assert worktime.measure([], "review", _at("11:00:00")) is None


@case
def the_time_of_a_ticket_survives_a_restart_because_it_is_read_from_the_journal():
    with _state_home():
        ticket = "a" * 32
        first = journal.Run.start(ticket=ticket)
        first.end("blocked", "", "session.question")
        second = journal.Run.start(ticket=ticket)
        second.end("done")
        found = journal.spans(ticket)[ticket]
        assert [span["status"] for span in found] == ["blocked", "done"], found
        assert journal.spans("b" * 32) == {}
        one = worktime.measure(found, "review")
        assert one and one["sessions"] == 2, one


# -- the GitHub App ----------------------------------------------------------

# A key drawn for these tests and for nothing else: 1024 bits, which GitHub would
# refuse and which signs the same way.
_TEST_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQDmIZaPsUal+WQoQUf6DdKVtrm4AzWXLgBsvcg81ivbuXW+m1m5
IJuOYi2udIK4e3bNdBXeehdLImlnauQEuZfu3pEyxcnWBiZU0bpPDO+JT5pKHMvN
8WFsqDItcnkqkh3ohbAghYqIAq9KiwzFe6YQ45WwtiDlVwBFjFM62Jm6QwIDAQAB
AoGAVljX80Zi6beveuMzrIEvOHl9KawamYTrJ+H1lc4OWr01jrUfbzTq6PuxhDm3
Kp04sFIUOou43bolrmYO9C7m8EVxG63oQEHD1UJF2VIVZ8F9YsWIR0dqUJ7eUbfr
95wqwlKJPDGFcyeQIVrRec0sGcrQ1upFdL37UgR1+Wwkl2ECQQDzeCB3MkxWJQAN
lss4H7yFs93E3LURrrUGf3wnGKtmECQm1OzvDyEhb3qyow1wPVd5G6ohzDTsZXQL
CWMRoTvJAkEA8fm5OOA5UQRG8IoV9QPVoOQGqaW2vtNCyj+bLfWgAZL6TjQkq/k4
EArlHXLFEnKgERAMFeYjK16KTEGZSm/zqwJBAJaJ7jkFRqH1GsVMObcoGF7rSfJR
LTwTtCaiaNebr07aKCBCg4WE601LKqiNnN+LbiyZ6GYhZ4/LYyb31OOvt9ECQQDb
JnudSl4+xOvm0HkgZe+l/r8WCJKg8z8LY14M2uemZVIzX8BSzKz8wpFNAXQAyDW2
Hl2Du+HgVohUlhjaNNhvAkAti2ev+Qs22EGfcCv4CiYwXpx/DC5lmkslVaHAiajP
XTFlXZshGFaUf2SnR17A2A8xR8x7/3K3FOTVofsXTQx6
-----END RSA PRIVATE KEY-----"""


@contextmanager
def _github_answering(answer):
    """GitHub replaced by `answer(method, path, headers, body) -> (status, dict)`.

    Yields the calls made, as (method, path, headers); the secrets file, the
    caches and the states are this test's own, and left as they were found.
    """
    calls: list[tuple[str, str, dict]] = []

    def send(method, url, headers, body):
        path = url[len(github_app.api()):]
        calls.append((method, path, headers))
        status, payload = answer(method, path, headers, body)
        return status, json.dumps(payload).encode()

    folder = Path(tempfile.mkdtemp())
    original, before = github_app._send, os.environ.get(C.SECRETS_PATH_ENV)
    github_app._send = send
    os.environ[C.SECRETS_PATH_ENV] = str(folder / "secrets.env")
    github_app._installations.clear()
    github_app._tokens.clear()
    try:
        yield calls
    finally:
        github_app._send = original
        if before is None:
            os.environ.pop(C.SECRETS_PATH_ENV, None)
        else:
            os.environ[C.SECRETS_PATH_ENV] = before
        github_app._installations.clear()
        github_app._tokens.clear()
        shutil.rmtree(folder, ignore_errors=True)


def _test_app(**changes) -> github_app.App:
    held = dict(id=42, slug="ponos-laptop", name="Ponos — laptop", owner="hermez", pem=_TEST_PEM,
                client_id="Iv1.abc", html_url="https://github.com/apps/ponos-laptop")
    held.update(changes)
    return github_app.App(**held)


@case
def a_github_app_jwt_is_rs256_signed_by_its_key_and_lasts_under_ten_minutes():
    import base64

    def part(text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    token = github_app.jwt(_test_app(), now=1_000_000)
    header, claims, signature = token.split(".")
    assert json.loads(part(header)) == {"alg": "RS256", "typ": "JWT"}
    said = json.loads(part(claims))
    assert said == {"iat": 1_000_000 - 60, "exp": 1_000_000 + 540, "iss": "Iv1.abc"}, said
    assert said["exp"] - said["iat"] <= 600
    # Checked with the public half: the signature, raised to `e`, is the padded digest.
    modulus, _ = github_app.private_key(_TEST_PEM)
    data = base64.b64decode("".join(_TEST_PEM.splitlines()[1:-1]))
    _, outer, _ = github_app._der(data, 0)
    exponent = int.from_bytes(github_app._children(outer)[2][1], "big")
    size = (modulus.bit_length() + 7) // 8
    opened = pow(int.from_bytes(part(signature), "big"), exponent, modulus).to_bytes(size, "big")
    import hashlib

    digest = hashlib.sha256(f"{header}.{claims}".encode()).digest()
    assert opened.startswith(b"\x00\x01\xff") and opened.endswith(github_app.SHA256_PREFIX + digest)
    # Without a client id, the app's id is who signs.
    assert json.loads(part(github_app.jwt(_test_app(client_id=""), now=5).split(".")[1]))["iss"] == "42"


@case
def the_manifest_code_is_exchanged_once_and_the_app_kept_with_the_secrets():
    def answer(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, []
        assert (method, path) == ("POST", "/app-manifests/abc123/conversions"), (method, path)
        assert "Authorization" not in headers
        return 201, {"id": 42, "slug": "ponos-laptop", "name": "Ponos — laptop",
                     "owner": {"login": "Hermez"}, "pem": _TEST_PEM, "client_id": "Iv1.abc",
                     "client_secret": "shh", "webhook_secret": "hook",
                     "html_url": "https://github.com/apps/ponos-laptop"}

    with _github_answering(answer) as calls:
        state = github_app.draw_state(organisation="hermez")
        code, where = web_github.callback("abc123", state)
        assert code == 303 and where.endswith("/apps/ponos-laptop/installations/new"), where
        assert [call[1] for call in calls] == ["/app-manifests/abc123/conversions"]
        kept = github_app.apps()
        assert [(app.id, app.slug, app.owner, app.client_secret) for app in kept] == [
            (42, "ponos-laptop", "Hermez", "shh")
        ]
        assert kept[0].pem == _TEST_PEM, "the key comes back whole, line breaks and all"
        file = C.secrets_path()
        assert file.stat().st_mode & 0o777 == 0o600
        # The console is shown names and places, never what signs or opens.
        shown = json.dumps(web_github.status())
        assert "PRIVATE KEY" not in shown and "shh" not in shown and "hook" not in shown
        # The same state a second time is a link already used.
        code, _ = web_github.callback("abc123", state)
        assert code == 400
        assert sum(call[1].startswith("/app-manifests/") for call in calls) == 1
        assert web_github.disconnect("ponos-laptop")["forgotten"] == "ponos-laptop"
        assert github_app.apps() == []


@case
def a_github_state_that_is_unknown_used_or_expired_is_refused_before_github_is_asked():
    with _github_answering(lambda *_: (500, {})) as calls:
        assert github_app.take_state("") is None
        assert github_app.take_state("made-up") is None
        code, page = web_github.callback("abc123", "made-up")
        assert code == 400 and "expired" in page
        late = github_app.draw_state()
        until, data = github_app._states[late]
        github_app._states[late] = (time.monotonic() - 1, data)
        assert github_app.take_state(late) is None
        good = github_app.draw_state(organisation="hermez")
        assert github_app.take_state(good) == {"organisation": "hermez"}
        assert github_app.take_state(good) is None
        assert calls == []


@case
def connecting_github_posts_a_manifest_for_an_account_or_an_organisation():
    mine = github_app.begin("http://127.0.0.1:8787/", "", "laptop")
    assert mine["action"].startswith("https://github.com/settings/apps/new?state=")
    theirs = github_app.begin("https://ponos.example", "@Hermez", "laptop")
    assert theirs["action"].startswith("https://github.com/organizations/Hermez/settings/apps/new?state=")
    said = json.loads(theirs["manifest"])
    assert said["name"] == "Ponos — laptop" and said["public"] is False
    assert said["redirect_url"] == "https://ponos.example/api/github/manifest/callback"
    assert said["setup_url"] == "https://ponos.example/api/github/installed"
    assert said["hook_attributes"]["active"] is False
    assert said["default_permissions"]["contents"] == "write"
    assert said["default_permissions"]["metadata"] == "read"
    assert not any(key.startswith("organization_") for key in said["default_permissions"])
    assert len(github_app.app_name("a-very-long-machine-name-indeed-yes")) <= github_app.LONGEST_NAME
    assert github_app.take_state(theirs["state"]) == {"organisation": "Hermez"}


@case
def an_installation_token_is_kept_and_renewed_before_it_lapses():
    minted: list[str] = []

    def answer(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, [{"id": 7, "account": {"login": "Hermez"}, "repository_selection": "all"}]
        assert (method, path) == ("POST", "/app/installations/7/access_tokens"), path
        assert headers["Authorization"].startswith("Bearer ey")
        minted.append(f"ghs_{len(minted)}")
        return 201, {"token": minted[-1], "expires_at": "2030-01-01T12:00:00Z"}

    with _github_answering(answer):
        github_app.save(_test_app())
        lapse = datetime(2030, 1, 1, 12, tzinfo=timezone.utc).timestamp()
        app = github_app.apps()[0]
        assert github_app.installation_token(app, 7, now=lapse - 3000) == "ghs_0"
        assert github_app.installation_token(app, 7, now=lapse - 700) == "ghs_0", "still fresh"
        assert github_app.installation_token(app, 7, now=lapse - 300) == "ghs_1", "renewed"
        assert minted == ["ghs_0", "ghs_1"]
        # The owner's repositories are worked with it, in place of any `gh` account.
        assert git_module.token_for("git@github.com:hermez/site.git", {"hermez": "salva"}) == "ghs_1"
        assert github_app.issued("ghs_1") and not github_app.issued("gho_personal")
        assert github_app.token("someone-else") == ""


@case
def a_session_and_a_push_on_an_installed_owner_carry_the_app_token_and_its_bot():
    def answer(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, [{"id": 7, "account": {"login": "hermez"}, "repository_selection": "selected"}]
        if path == "/app/installations/7/access_tokens":
            return 201, {"token": "ghs_session", "expires_at": "2099-01-01T00:00:00Z"}
        if path == "/users/ponos-laptop%5Bbot%5D":
            return 200, {"id": 99}
        if path.startswith("/installation/repositories"):
            return 200, {"repositories": [{"full_name": "hermez/site"}]}
        raise AssertionError(path)

    with _github_answering(answer):
        github_app.save(_test_app())
        given = github_app.session_environment("hermez")
        assert given["GH_TOKEN"] == given["GITHUB_TOKEN"] == "ghs_session"
        assert given["GIT_AUTHOR_NAME"] == given["GIT_COMMITTER_NAME"] == "ponos-laptop[bot]"
        assert given["GIT_AUTHOR_EMAIL"] == "99+ponos-laptop[bot]@users.noreply.github.com"
        assert "ghs_session" not in "".join(
            value for name, value in given.items() if name.startswith("GIT_CONFIG")
        ), "the token is read from the environment, never written into a git setting"
        assert github_app.session_environment("someone-else") == {}
        assert github_app.covers("hermez/site", "hermez") is True
        assert github_app.covers("hermez/other", "hermez") is False
        # What the runner itself runs with an app token: the token, and git told how to use it.
        seen = git_module.run(
            ["sh", "-c", 'echo "$GH_TOKEN $GIT_CONFIG_COUNT"'],
            token=git_module.token_for("https://github.com/hermez/site", None),
        )
        assert seen.out.split()[0] == "ghs_session" and int(seen.out.split()[1]) >= 5, seen.out
        # A `gh` account's token is passed as it always was, and nothing more.
        plain = git_module.run(["sh", "-c", 'echo "$GH_TOKEN ${GIT_CONFIG_COUNT:-none}"'], token="gho_mine")
        assert plain.out == "gho_mine none" or plain.out.startswith("gho_mine "), plain.out


@case
def without_a_github_app_the_gh_accounts_answer_as_before():
    with _github_answering(lambda *_: (500, {})) as calls:
        assert github_app.apps() == []
        assert git_module.token_for("hermez/site", {}) == ""
        assert github_app.covers("hermez/site", "hermez") is None
        assert github_app.describe() == []
        assert calls == [], "nothing is asked of GitHub when no app is connected"


@case
def git_is_given_the_app_token_through_its_environment_and_never_in_a_value():
    environment = github_app.git_environment(base={"GIT_CONFIG_COUNT": "2"})
    assert environment["GIT_CONFIG_COUNT"] == "7"
    assert "GIT_CONFIG_KEY_0" not in environment, "what was already carried stays where it was"
    assert environment["GIT_CONFIG_KEY_2"] == "credential.https://github.com.helper"
    assert environment["GIT_CONFIG_VALUE_2"] == ""
    assert "$GH_TOKEN" in environment["GIT_CONFIG_VALUE_3"]
    assert environment["GIT_CONFIG_VALUE_5"] == "git@github.com:"
    # A session's helper answers git with a token, for github.com only.
    out = io.StringIO()
    before = {name: os.environ.get(name) for name in ("GH_TOKEN", "PONOS_GITHUB_LAPSES")}
    os.environ.update(GH_TOKEN="ghs_held", PONOS_GITHUB_LAPSES=str(int(time.time()) + 3000))
    try:
        github_app.helper(["get"], read=lambda: "protocol=https\nhost=github.com\npath=hermez/site.git\n", out=out)
        assert out.getvalue() == "username=x-access-token\npassword=ghs_held\n", out.getvalue()
        elsewhere = io.StringIO()
        github_app.helper(["get"], read=lambda: "protocol=https\nhost=gitlab.com\n", out=elsewhere)
        assert elsewhere.getvalue() == ""
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# -- the vault ---------------------------------------------------------------


@contextmanager
def _tools(scripts: dict[str, str]):
    """Fake `pass`, `secret-tool` or `bw` at the head of the PATH, as Python scripts."""
    home = Path(tempfile.mkdtemp())
    for name, body in scripts.items():
        (home / name).write_text("#!" + sys.executable + "\nimport sys, os\n" + body)
        (home / name).chmod(0o755)
    previous = os.environ["PATH"]
    os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
    try:
        yield home
    finally:
        os.environ["PATH"] = previous


@case
def the_vault_is_read_project_by_project_and_checked():
    """`[vault]` grants each project its own keys, and says what it cannot hand over."""
    settings = _config(
        '[vault]\nprovider = "pass"\n'
        '[vault.projects]\nLeadz = ["LEADZ_DOKPLOY_TOKEN"]\n'
        '[vault.projects.Ponos]\nNPM_TOKEN = "hermez-npm"\nGH_TOKEN = "keyring:service=gh"\n'
        'ANTHROPIC_API_KEY = "stolen"\nPONOS_NOTION_TOKEN = "stolen"\n"not a name" = "x"\n'
    ).vault
    assert settings.provider == "pass"
    assert settings.granted("leadz") == {"LEADZ_DOKPLOY_TOKEN": "LEADZ_DOKPLOY_TOKEN"}
    assert settings.granted(" PONOS ") == {"NPM_TOKEN": "hermez-npm", "GH_TOKEN": "keyring:service=gh"}
    assert settings.granted("Opoil") == {}, "a project the table does not name is given nothing"
    joined = "\n".join(settings.problems)
    assert "ANTHROPIC_API_KEY is the runner's own" in joined, joined
    assert "PONOS_NOTION_TOKEN is the runner's own" in joined, joined
    assert "'not a name' is not an environment variable name" in joined, joined
    assert C.Config.__dataclass_fields__["vault"]  # and an empty file has a vault too
    empty = _config("").vault
    assert empty.provider == "env" and empty.projects == {} and empty.problems == ()
    typo = _config('[vault]\nprovider = "1pass"\n').vault
    assert "vault.provider = '1pass'" in typo.problems[0]
    assert vault.where("pass:hermez/npm", "env") == ("pass", "hermez/npm")
    assert vault.where("service=gh account=a:b", "keyring") == ("keyring", "service=gh account=a:b")
    example = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    assert "[vault]" in example and "[vault.projects]" in example


@case
def each_provider_reads_a_secret_and_tells_a_missing_one_from_a_locked_vault():
    vault.forget()
    os.environ["PONOS_TEST_VAULT"] = "from-the-environment"
    try:
        environment = vault.provider("env", {"IN_FILE": "from-secrets-env"})
        assert environment.read("PONOS_TEST_VAULT") == "from-the-environment"
        assert environment.read("IN_FILE") == "from-secrets-env"
        assert environment.read("NOWHERE") == ""
    finally:
        os.environ.pop("PONOS_TEST_VAULT")
    with _tools({
        "pass": (
            "if sys.argv[2] == 'hermez/npm': print('npm_granular_abcdef\\nlogin: hermez')\n"
            "else: sys.stderr.write('Error: x is not in the password store.\\n'); sys.exit(1)\n"
        ),
        "secret-tool": (
            "if sys.argv[1:] == ['lookup', 'service', 'ponos', 'username', 'npm']: print('kr_secret_value', end='')\n"
            "elif sys.argv[1:] == ['lookup', 'service', 'gh', 'account', 'me']: print('kr_github_value', end='')\n"
            "else: sys.exit(1)\n"
        ),
        "bw": (
            "assert os.environ['BW_SESSION'] == 'unlocked'\n"
            "if sys.argv[3] == 'dokploy': print('bw_dokploy_value')\n"
            "else: sys.stderr.write('Not found.'); sys.exit(1)\n"
        ),
    }):
        assert vault.provider("pass").read("hermez/npm") == "npm_granular_abcdef", "the first line only"
        assert vault.provider("pass").read("other") == ""
        assert vault.provider("keyring").read("npm") == "kr_secret_value"
        assert vault.provider("keyring").read("service=gh account=me") == "kr_github_value"
        assert vault.provider("keyring").read("absent") == ""
        try:
            vault.provider("bitwarden", {}).read("dokploy")
        except vault.VaultError as error:
            assert "BW_SESSION" in str(error)
        else:
            raise AssertionError("a locked Bitwarden is not an empty one")
        unlocked = vault.provider("bitwarden", {"BW_SESSION": "unlocked"})
        assert unlocked.read("dokploy") == "bw_dokploy_value"
        assert unlocked.read("absent") == ""
        found = vault.read(
            {"NPM_TOKEN": "hermez/npm", "DOKPLOY": "bitwarden:dokploy", "GONE": "nothing-here"},
            "pass",
            {"BW_SESSION": "unlocked"},
        )
        assert found.values == {"NPM_TOKEN": "npm_granular_abcdef", "DOKPLOY": "bw_dokploy_value"}
        assert found.missing == ["GONE (pass: no such item)"], found.missing
        assert "npm_granular_abcdef" not in "".join(found.missing)
        assert vault.mask("token npm_granular_abcdef here") == "token *** here", "read is remembered"
    try:
        vault.provider("onepassword")
    except vault.VaultError as error:
        assert "env, keyring, pass, bitwarden" in str(error)
    else:
        raise AssertionError("an unknown provider is said, not guessed")
    vault.forget()


@case
def a_secret_read_is_masked_wherever_it_would_be_written():
    vault.forget()
    try:
        vault.remember("abc")  # too short to be masked without masking the code
        assert vault.mask("abc") == "abc"
        vault.remember('tok"en\\value')
        vault.remember("npm_0123456789")
        assert vault.mask("NPM=npm_0123456789!") == "NPM=***!"
        assert vault.mask(json.dumps({"x": 'tok"en\\value'})) == '{"x": "***"}', "the JSON spelling too"
        assert vault.masked({"a": ["npm_0123456789", 3], "b": {"c": "ok"}}) == {
            "a": ["***", 3], "b": {"c": "ok"}
        }
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "x.err"
            stderr.write_text("auth failed for npm_0123456789\n")
            vault.scrub(stderr)
            assert stderr.read_text() == "auth failed for ***\n"
            # The Markdown board.
            board = files.Board(Path(directory) / "board", _config("").notion)
            database = board.resolve_database("Tickets")
            page = board.create_row(database, "Publish npm_0123456789")
            board.comment(page, "done with npm_0123456789")
            written = "".join(path.read_text() for path in Path(directory, "board").rglob("*.md"))
            assert "npm_0123456789" not in written and "***" in written, written
        # Notion: what is sent, whatever the call.
        sent: list[bytes] = []

        class Answer:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"{}"

        original = notion.urllib.request.urlopen
        notion.urllib.request.urlopen = lambda request, timeout=0: sent.append(request.data) or Answer()
        try:
            notion.Client("ntn_test").comment("p", "the key is npm_0123456789")
        finally:
            notion.urllib.request.urlopen = original
        assert sent and b"npm_0123456789" not in sent[0] and b"***" in sent[0], sent
    finally:
        vault.forget()


@case
def a_session_given_a_secret_never_writes_it_down():
    """What the session prints of its key is masked in its transcript, answer and stderr."""
    vault.forget()
    vault.remember("npm_supersecret_42")
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "sys.stdin.read()\n"
            "sys.stderr.write('debug ' + os.environ['NPM_TOKEN'] + '\\n')\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'using ' + os.environ['NPM_TOKEN']}]}}))\n"
            "print(json.dumps({'type': 'result', 'result': 'published with ' + os.environ['NPM_TOKEN'] + '\\nRESULT: ok — done', 'session_id': 's'}))\n"
        )
        (home / "claude").chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        seen: list[dict] = []
        try:
            outcome = session.run(
                "go", cwd=home, log=home / "s.jsonl", timeout_minutes=1,
                environment={"NPM_TOKEN": "npm_supersecret_42"}, on_event=seen.append,
            )
        finally:
            os.environ["PATH"] = previous
            vault.forget()
        assert outcome.ok, outcome.error
        assert "npm_supersecret_42" not in outcome.answer and "***" in outcome.answer
        assert "npm_supersecret_42" not in json.dumps(seen)
        assert "npm_supersecret_42" not in (home / "s.jsonl").read_text()
        assert (home / "s.err").read_text() == "debug ***\n"


@case
def a_ticket_session_is_given_its_project_secrets_by_name_only():
    vault.forget()
    runner = _bare_runner(None)
    runner.dry_run = False
    runner.config = _config('[vault]\n[vault.projects]\nLeadz = ["PONOS_TEST_LEADZ_KEY"]\n')
    os.environ["PONOS_TEST_LEADZ_KEY"] = "leadz_secret_value"
    try:
        leadz = type("J", (), {"project": type("P", (), {"name": "Leadz"})()})()
        other = type("J", (), {"project": type("P", (), {"name": "Ponos"})()})()
        assert runner._secrets(other) == {}, "nobody else's keys"
    finally:
        os.environ.pop("PONOS_TEST_LEADZ_KEY")
    # A PONOS_ name is refused for a project: the runner's own namespace.
    assert "PONOS_TEST_LEADZ_KEY is the runner's own" in runner.config.vault.problems[0]
    runner.config = _config('[vault]\n[vault.projects]\nLeadz = ["LEADZ_TEST_KEY"]\n')
    os.environ["LEADZ_TEST_KEY"] = "leadz_secret_value"
    try:
        assert runner._secrets(leadz) == {"LEADZ_TEST_KEY": "leadz_secret_value"}
        assert vault.mask("leadz_secret_value") == "***"
    finally:
        os.environ.pop("LEADZ_TEST_KEY")
        vault.forget()
    text = prompt.build(
        prompt.DOCUMENT, project="Leadz", title="t", body="b", repo="r", branch="b",
        base="main", url="u", secrets=["LEADZ_TEST_KEY"],
    )
    assert "# Secrets" in text and "`LEADZ_TEST_KEY`" in text and "leadz_secret_value" not in text
    assert "# Secrets" not in prompt.build(
        prompt.DEFAULT, project="p", title="t", body="b", repo="r", branch="b", base="m", url="u"
    )



def _serve_status(name: str, port: int = 8787, funnel: bool = True, extra: dict | None = None) -> str:
    local = f"http://127.0.0.1:{port}"
    web = {
        f"{name}:8443": {"Handlers": {"/": {"Proxy": local}}},
        f"{name}:443": {
            "Handlers": {path: {"Proxy": local + path} for path in ("/mcp", "/oauth", "/.well-known")}
        },
    }
    web[f"{name}:443"]["Handlers"].update(extra or {})
    return json.dumps({"Web": web, "AllowFunnel": {f"{name}:443": True} if funnel else {}})


@case
def tailscale_publishes_the_mcp_paths_on_the_funnel_port_and_the_console_on_another():
    """Funnel is per host and port: the console on 443 beside /mcp would be public."""
    from ponos import tailscale

    lines = tailscale.commands(8787)
    assert lines[0] == ["serve", "--bg", "--https=8443", "http://127.0.0.1:8787"], lines[0]
    funnelled = [line for line in lines if line[0] == "funnel"]
    assert [line[3] for line in funnelled] == ["--set-path=/mcp", "--set-path=/oauth", "--set-path=/.well-known"]
    assert all(line[2] == "--https=443" for line in funnelled)
    assert all(not line[-1].endswith(":8787") for line in funnelled), "the root must never be funnelled"


@case
def a_request_through_the_funnel_reaches_the_mcp_doors_and_nothing_else():
    import urllib.error
    import urllib.request

    from ponos import tailscale
    from ponos.web import server as web_server

    assert tailscale.funnel_allowed("/mcp") and tailscale.funnel_allowed("/oauth/token")
    assert tailscale.funnel_allowed("/.well-known/oauth-protected-resource/mcp")
    assert not tailscale.funnel_allowed("/") and not tailscale.funnel_allowed("/api/tickets")
    assert not tailscale.funnel_allowed("/mcpx"), "a prefix of a name is not the path"

    with _state_home(), _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]

        def status(path: str, funnel: bool, method: str = "GET") -> int:
            headers = {tailscale.FUNNEL_HEADER: "?1"} if funnel else {}
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}", headers=headers, method=method,
                data=b"{}" if method == "POST" else None,
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code

        try:
            assert status("/api/tickets?token=tok", funnel=True) == 404
            assert status("/healthz", funnel=True) == 404
            assert status("/api/tickets", funnel=True, method="POST") == 404
            assert status("/.well-known/oauth-protected-resource/mcp", funnel=True) == 200
            assert status("/mcp", funnel=True, method="POST") == 401, "the keys still apply"
            assert status("/healthz", funnel=False) == 200, "inside the tailnet nothing changes"
        finally:
            console.shutdown()
            console.server_close()


@case
def tailscale_serve_status_is_read_as_in_place_only_when_both_doors_are_exactly_ours():
    from ponos import tailscale

    name = "laptop.tail1234.ts.net"
    assert tailscale.configured(_serve_status(name), name, 8787)
    assert not tailscale.configured("{}", name, 8787), "nothing published yet"
    assert not tailscale.configured("not json", name, 8787)
    assert not tailscale.configured(_serve_status(name, port=9000), name, 8787), "the console moved"
    assert not tailscale.configured(_serve_status(name, funnel=False), name, 8787), "funnel not allowed"
    extra = {"/": {"Proxy": "http://127.0.0.1:8787"}}
    assert not tailscale.configured(_serve_status(name, extra=extra), name, 8787), (
        "a root handler on the funnel port is the console, public"
    )


@case
def the_tailscale_watch_waits_for_the_tailnet_then_publishes_and_republishes_after_a_drift():
    import subprocess

    from ponos import tailscale

    name = "laptop.tail1234.ts.net"
    state = {"backend": "Stopped", "serve": "{}"}
    ran: list[list[str]] = []

    def run(arguments: list[str]) -> "subprocess.CompletedProcess[str]":
        ran.append(arguments)
        out = ""
        if arguments[:2] == ["status", "--json"]:
            out = json.dumps({"BackendState": state["backend"], "Self": {"DNSName": name + "."}})
        elif arguments[:2] == ["serve", "status"]:
            out = state["serve"]
        elif arguments[0] in ("serve", "funnel"):
            state["serve"] = _serve_status(name)
        return subprocess.CompletedProcess(arguments, 0, out, "")

    said: list[str] = []
    ticks = iter(range(100))

    def sleep(_: float) -> None:
        step = next(ticks)
        if step == 1:
            state["backend"] = "Running"  # the lid is open, the Wi-Fi is back
        if step == 4:
            state["serve"] = "{}"  # tailscaled lost it

    tailscale.watch(8787, 30, run=run, sleep=sleep, log=said.append, rounds=7)
    published = [line for line in ran if line[0] in ("serve", "funnel") and "status" not in line]
    assert len(published) == 2 * 4, ("once on connecting, once after the drift", published)
    assert said[0].startswith("tailscale is Stopped"), said
    assert sum("serving" in line for line in said) == 2, said


@case
def a_missing_tailscale_binary_is_said_once_by_the_watcher_and_does_not_stop_it():
    from ponos import tailscale

    said: list[str] = []

    def run(arguments: list[str]):
        raise tailscale.TailscaleError("tailscale is not installed")

    tailscale.watch(8787, 1, run=run, sleep=lambda _: None, log=said.append, rounds=3)
    assert said == ["tailscale is not installed"], said



class _HealthBoard:
    """The few calls `health` makes of a Notion board, over a database held in memory."""

    def __init__(self, properties: dict[str, dict]) -> None:
        self.properties = properties
        self.added: dict = {}

    def forget_database(self, database_id: str) -> None:
        pass

    def database(self, database_id: str) -> dict:
        return {"properties": self.properties}

    def schema(self, database_id: str) -> dict[str, str]:
        return {name: prop["type"] for name, prop in self.properties.items()}

    def options(self, database_id: str, name: str) -> list[str]:
        prop = self.properties.get(name) or {}
        return [option["name"] for option in (prop.get(prop.get("type", "")) or {}).get("options", [])]

    def add_properties(self, database_id: str, properties: dict) -> None:
        self.added.update(properties)


def _health_board(skip: tuple[str, ...] = (), statuses: tuple[str, ...] = ()):
    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    schema = provision.tickets_schema(settings, "projects", "agents")
    properties = {name: {"type": next(iter(shape)), **shape} for name, shape in schema.items() if name not in skip}
    if statuses:
        properties[settings.prop("status")] = {
            "type": "select", "select": {"options": [{"name": name} for name in statuses]},
        }
    return settings, _HealthBoard(properties)


@case
def health_says_nothing_of_a_board_that_is_complete():
    from ponos import health

    settings, board = _health_board()
    config = _config("")
    config.notion = settings
    found = health._schema(config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents"))
    assert [check.state for check in found] == [health.OK, health.OK], found


@case
def health_offers_to_add_the_missing_properties_and_does_it_only_once_confirmed():
    from ponos import health

    settings, board = _health_board(skip=("Runner", "Progress"))
    config = _config("")
    config.notion = settings
    found = health._schema(config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents"))
    columns = next(check for check in found if check.code == "notion.columns")
    assert columns.state == health.ERROR
    assert "“Runner”" in columns.params["missing"] and "“Progress”" in columns.params["missing"]
    assert columns.fix and columns.fix["action"] == "notion_columns"
    assert "“Runner”" in columns.text(columns.fix["confirm"].replace("{{missing}}", columns.fix["missing"])), "the dialog names them"

    class Client(_HealthBoard):
        def resolve_database(self, identifier: str) -> str:
            return "db"

    client = Client(board.properties)
    original = workspace.resolve
    workspace.resolve = lambda backend, notion_settings: workspace.Workspace(tickets="db", projects="projects", agents="agents")
    try:
        try:
            health.fix(config, client, "notion_columns")
        except PermissionError:
            pass
        else:
            raise AssertionError("a fix is never made unasked")
        assert not client.added, "nothing was written before the confirmation"
        health.fix(config, client, "notion_columns", confirmed=True)
    finally:
        workspace.resolve = original
    assert set(client.added) == {"Runner", "Progress"}, client.added


@case
def health_adds_a_missing_status_to_a_select_and_only_says_how_on_a_real_status():
    from ponos import health

    settings, board = _health_board(statuses=("Ready", "In progress", "Done"))
    config = _config("")
    config.notion = settings
    found = health._schema(config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents"))
    statuses = next(check for check in found if check.code == "notion.statuses")
    assert statuses.state == health.ERROR and statuses.fix and statuses.fix["action"] == "notion_statuses"
    assert "“Failed”" in statuses.params["missing"]

    name = settings.prop("status")
    board.properties[name] = {"type": "status", "status": {"options": [{"name": "Ready"}]}}
    found = health._schema(config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents"))
    statuses = next(check for check in found if check.code == "notion.statuses")
    assert statuses.fix is None and statuses.steps, "Notion cannot widen a status from outside"


@case
def health_reports_a_project_whose_folder_is_gone_and_one_with_no_remote():
    from ponos import health

    config = _config("")
    gone = health._project(config, {"id": "1", "name": "Ghost", "repository": "", "path": "/nonexistent/ghost"})
    assert [check.state for check in gone] == [health.ERROR] and gone[0].code == "projects.path"
    assert "Ghost" in gone[0].text(gone[0].said)

    # A repository to clone is not a mistake: it is fetched when its first ticket starts.
    cloned = health._project(config, {"id": "2", "name": "Later", "repository": "acme/later", "path": ""})
    assert [check.state for check in cloned] == [health.WARN]

    repo = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    bare = health._project(config, {"id": "3", "name": "Bare", "repository": "", "path": str(repo)})
    assert [check.code for check in bare] == ["projects.path", "projects.remote"]
    assert bare[1].state == health.ERROR and bare[1].steps


def main() -> int:
    # Claude Code's own store, pointed at an empty directory for the whole
    # suite. Everything here is pure, and "how much of this machine's
    # subscription is spent" is the least pure fact there is: a laptop at 96 %
    # would otherwise park tickets in a test about something else entirely, and
    # a CI runner with no store at all would take a different road again. The
    # tests that are *about* the reading say so themselves — see `_usage`.
    os.environ["CLAUDE_CONFIG_DIR"] = tempfile.mkdtemp()
    # The runner's own state, for two reasons: a test that runs a session writes
    # its run into the local journal, and opening the real `ponos.db` would
    # migrate it and set aside the JSON files the installed runner still reads.
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    # GitHub, for a machine that has connected an app: an address nothing
    # listens on, so a test that reaches `git.token_for` falls back on `gh` at
    # once rather than asking the real GitHub for a token. The tests about the
    # app replace the transport itself — see `_github_answering`.
    os.environ[github_app.API_ENV] = "http://127.0.0.1:9"
    failures = 0
    for function in CASES:
        try:
            function()
        except Exception:  # noqa: BLE001 — a test runner reports, it does not raise
            failures += 1
            print(f"  ✗ {function.__name__}")
            print("".join("      " + line for line in traceback.format_exc().splitlines(True)))
        else:
            print(f"  ✓ {function.__name__}")
    total = len(CASES)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
