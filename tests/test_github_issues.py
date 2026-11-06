"""`github_issues.py`: the issues of a repository, read as the tickets of a board."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from support import _config, case

from ponos import config as C
from ponos import github_issues, store
from ponos.github_issues import MARKER, Issues, issue_id


class _GitHub(Issues):
    """`Issues` over a GitHub held in memory: the requests it makes are the ones answered."""

    def __init__(self, root: Path, repositories: str = '["acme/site"]') -> None:
        config = _config(f'[storage]\nmode = "github"\n[issues]\nrepositories = {repositories}\n')
        super().__init__(root, config.notion, config.issues, config.github)
        self.issues: dict[tuple[str, int], dict[str, Any]] = {}
        self.said: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def open_issue(
        self, number: int, title: str, *labels: str, repository: str = "acme/site"
    ) -> None:
        self.issues[(repository, number)] = {
            "number": number,
            "title": title,
            "body": f"Le détail de {title}.",
            "state": "open",
            "html_url": f"https://github.com/{repository}/issues/{number}",
            "labels": [{"name": name} for name in labels],
        }

    def labels_of(self, number: int, repository: str = "acme/site") -> list[str]:
        return sorted(one["name"] for one in self.issues[(repository, number)]["labels"])

    def call(self, repository: str, method: str, path: str, **fields: Any) -> Any:
        self.requests.append((method, path, fields))
        parts = path.split("?")[0].split("/")
        if parts[0] != "issues":
            return {}
        if len(parts) == 1:
            wanted = dict(pair.split("=") for pair in path.split("?")[1].split("&"))
            if wanted["page"] != "1":
                return []
            return [
                one
                for (name, _), one in self.issues.items()
                if name == repository
                and one["state"] == wanted["state"]
                and {"name": wanted["labels"]} in one["labels"]
            ]
        issue = self.issues[(repository, int(parts[1]))]
        if len(parts) == 2:
            issue.update({k: v for k, v in fields.items() if method == "PATCH"})
            return issue
        if parts[2] == "comments":
            held = self.said.setdefault((repository, int(parts[1])), [])
            if method == "POST":
                held.append({"id": len(held), "body": fields["body"], "user": {"login": "me"}})
            return held if "page=1" in path else []
        if parts[2] == "labels" and method == "POST":
            issue["labels"] += [{"name": name} for name in fields["labels"]]
        if parts[2] == "labels" and method == "DELETE":
            gone = parts[3].replace("%3A", ":")
            issue["labels"] = [one for one in issue["labels"] if one["name"] != gone]
        return None


def _board(**keywords: Any) -> _GitHub:
    return _GitHub(Path(tempfile.mkdtemp()) / "board", **keywords)


@case
def the_github_storage_mode_opens_the_issues_store() -> None:
    root = tempfile.mkdtemp()
    configuration = _config(
        f'[storage]\nmode = "github"\npath = "{root}"\n[issues]\nrepositories = ["acme/site"]\n'
    )
    assert isinstance(store.open(configuration), Issues)
    assert configuration.issues.label == "ponos"
    assert configuration.storage.notion is False and configuration.storage.markdown is True
    configuration.require_usable()

    # A board of issues that names no repository has nothing to read.
    empty = _config('[storage]\nmode = "github"\n')
    try:
        empty.require_usable()
    except C.ConfigError as error:
        assert "issues.repositories" in str(error)
    else:
        raise AssertionError("no repository, and nothing said")


@case
def an_issue_page_is_found_again_from_its_identifier_alone() -> None:
    board = _board(repositories='["acme/site", "acme/api"]')
    first, second = issue_id("acme/site", 7), issue_id("acme/api", 7)
    assert len(first) == 32 and first != second and first[-8:] != second[-8:]
    assert board._decode(first) == ("acme/site", 7)
    assert board._decode(second) == ("acme/api", 7)
    assert board._decode(issue_id("elsewhere/repo", 7)) is None
    assert board._decode("x" * 32) is None


@case
def an_open_issue_with_the_label_is_a_ready_ticket_and_the_others_are_not() -> None:
    board = _board()
    board.open_issue(1, "Corriger le menu", "ponos", "type:code", "subtype:bug", "priority:80")
    board.open_issue(2, "Une idée", "enhancement")
    board.open_issue(3, "Déjà fait", "ponos", "ponos:review")
    tickets = {page.title: page for page in board.query("tickets")}
    assert set(tickets) == {"Corriger le menu", "Déjà fait"}

    page = tickets["Corriger le menu"]
    settings = board.settings()
    assert store.read(page, settings.prop("status")) == "ready"
    assert store.read(page, settings.prop("type")) == "Code"
    assert store.read(page, settings.prop("subtype")) == "Bug"
    assert store.read(page, settings.prop("priority")) == 80
    assert page.url == "https://github.com/acme/site/issues/1"
    assert page.raw["issue"] == {"repository": "acme/site", "number": 1}
    assert github_issues.closing(page) == "Closes acme/site#1"
    assert store.read(tickets["Déjà fait"], settings.prop("status")) == "review"

    [project] = board.query("projects")
    assert store.read(page, settings.prop("project")) == [project.id]
    assert store.read(project, "Repository") == "acme/site"
    assert board.blocks_text(page.id, live=False) == "Le détail de Corriger le menu."


@case
def moving_a_ticket_is_one_status_label_taken_off_and_another_put_on() -> None:
    board = _board()
    board.open_issue(1, "Corriger", "ponos", "bug", "type:bug")
    [page] = board.query("tickets")
    settings = board.settings()
    status, kind, priority = (settings.prop(key) for key in ("status", "type", "priority"))

    board.update("tickets", page.id, {status: "progress", kind: "Code", priority: 60})
    assert board.labels_of(1) == [
        "bug",
        "ponos",
        "ponos:progress",
        "priority:60",
        "type:bug",
        "type:code",
    ]  # fmt: skip — a team's own `type:bug` is its own
    board.update("tickets", page.id, {status: "blocked"})
    assert "ponos:progress" not in board.labels_of(1) and "ponos:blocked" in board.labels_of(1)
    board.update("tickets", page.id, {status: "ready"})
    assert board.labels_of(1) == ["bug", "ponos", "priority:60", "type:bug", "type:code"]
    assert board.issues[("acme/site", 1)]["state"] == "open"

    board.update("tickets", page.id, {status: "done", settings.prop("cost"): 0.5})
    assert board.issues[("acme/site", 1)]["state"] == "closed"
    # What GitHub has no column for stays on the file, and is read back.
    assert store.read(board.page(page.id), settings.prop("cost")) == 0.5
    assert store.read(board.page(page.id), status) == "done"


@case
def a_ticket_closed_on_github_is_done_on_the_board() -> None:
    board = _board()
    board.open_issue(1, "Corriger", "ponos", "ponos:review")
    [page] = board.query("tickets")
    board.issues[("acme/site", 1)]["state"] = "closed"
    board._pulled = 0.0
    [again] = board.query("tickets")
    assert again.id == page.id
    assert store.read(again, board.settings().prop("status")) == "done"


@case
def what_a_run_says_is_a_comment_and_who_said_it_is_told_by_a_marker() -> None:
    board = _board()
    board.open_issue(4, "Choisir", "ponos")
    [page] = board.query("tickets")
    board.comment(page.id, "Une ou deux pages ?")
    board.append_markdown(page.id, "\n---\nLe compte rendu.")
    board.said[("acme/site", 4)].append({"id": 9, "body": "oui", "user": {"login": "salva"}})

    raised = board.said[("acme/site", 4)]
    assert all(one["body"].startswith(MARKER) for one in raised[:2])
    said = board.comments(page.id)
    assert [(one.text, one.created_by) for one in said] == [
        ("Une ou deux pages ?", "ponos"),
        ("Le compte rendu.", "ponos"),
        ("oui", "salva"),
    ]
    assert len({one.discussion_id for one in said}) == 1, "GitHub has one discussion per issue"
    assert board.me() == "ponos"


@case
def an_issue_is_closed_as_not_planned_never_deleted() -> None:
    board = _board()
    board.open_issue(5, "Abandonné", "ponos")
    [page] = board.query("tickets")
    board.trash(page.id)
    assert board.issues[("acme/site", 5)]["state"] == "closed"
    assert board.issues[("acme/site", 5)]["state_reason"] == "not_planned"
    assert board.query("tickets") == [], "and it is off the board"


@case
def doctor_checks_the_repository_the_rights_and_the_label() -> None:
    from ponos import health

    board = _board()
    config = _config('[storage]\nmode = "github"\n[issues]\nrepositories = ["acme/site", "nope"]\n')

    def call(repository: str, method: str, path: str, **fields: Any) -> Any:
        if path == "":
            return {"has_issues": True, "permissions": {"push": False, "triage": False}}
        raise store.Missing(f"{repository}/{path}: HTTP 404")

    board.call = call  # type: ignore[method-assign]  # the GitHub that answers
    found = health._issues(config, board)
    by_state = {(check.code, check.state) for check in found}
    assert ("github.issues", health.ERROR) in by_state, "a read-only account cannot label"
    assert ("github.label", health.WARN) in by_state, "no such label"
    texts = [check.text(check.said) for check in found]
    assert any("cannot label or comment" in text for text in texts), texts
    assert any("nope is not a repository name" in text for text in texts), texts
    assert health._issues(config, object()) == [], "only a board of issues is asked"  # type: ignore[arg-type]
