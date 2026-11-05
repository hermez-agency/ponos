"""`provision.py`: `ponos init`, building a board and completing one without breaking it."""

from __future__ import annotations

import contextlib
import getpass
import io
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from support import _Board, _http_answering, _settings, case

from ponos import config as C
from ponos import provision, store

# -- provisioning ------------------------------------------------------------


@case
def a_bare_page_becomes_the_whole_board() -> None:
    board = _Board()
    report = provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake board

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
    # « Après » points at the tickets themselves, so it comes once they exist.
    assert schema["Après"]["relation"]["database_id"] == "db-tickets"
    # …and are spelled the way the API accepts: the kind is named *and* given
    # its empty object, or the request is rejected as `undefined`.
    for name in ("Project", "Agent"):
        assert schema[name]["relation"]["type"] == "single_property"
        assert schema[name]["relation"]["single_property"] == {}

    # A status property cannot be created through the API; a select can, and the
    # runner reads both. Every column must be there, validated included.
    options = [option["name"] for option in schema["Status"]["select"]["options"]]
    assert options == [
        "Ready",
        "In progress",
        "In review",
        "Validated",
        "Done",
        "Failed",
        "Blocked",
        "Paused",
        "Cancelled",
    ]
    # And the credit is not one of them: a ticket nothing was started for has not
    # moved, so it is ticked where it stands rather than sent to an eighth column.
    assert schema["Waiting for credit"] == {"checkbox": {}}

    assert board.appended, "the context page is seeded rather than left blank"


@case
def running_init_twice_changes_nothing() -> None:
    board = _Board()
    provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake board
    before = dict(board._schemas["db-tickets"])
    board.created.clear()

    second = provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake board
    assert board.created == [], "nothing is created a second time"
    assert board._schemas["db-tickets"] == before
    assert second.tickets == "db-tickets"
    assert all(verb == "kept" for verb, _ in second.steps), second.steps


@case
def init_completes_a_board_that_predates_a_column() -> None:
    """The second reason this command exists: adding what a version did not have.

    A board built before `Scheduled` gets the column rather than a line in a
    changelog telling its owner to add it by hand.
    """
    board = _Board(
        databases={"root": {"ponos": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={
            "db-tickets": {
                "Name": {"title": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Ready", "color": "blue"},
                            {"name": "Mine", "color": "purple"},
                        ]
                    }
                },
            }
        },
    )
    provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake board

    schema = board._schemas["db-tickets"]
    assert "Scheduled" in schema and "Cost" in schema

    # Options are merged, never replaced: a column somebody added is still there.
    options = [option["name"] for option in schema["Status"]["select"]["options"]]
    assert "Mine" in options and "Blocked" in options
    assert options.index("Mine") < options.index("Blocked"), "what exists keeps its place"


@case
def a_real_status_column_is_reported_rather_than_patched() -> None:
    """The one thing the API cannot do, said out loud instead of discovered late.

    A `status` property built in Notion's own interface accepts no new options
    from the API. Silence here would surface as a ticket failing to be marked
    "Blocked", weeks later, at the end of a session.
    """
    board = _Board(
        databases={"root": {"ponos": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={
            "db-tickets": {
                "Name": {"title": {}},
                "Status": {
                    "status": {
                        "options": [
                            {"name": "Ready"},
                            {"name": "In progress"},
                        ]
                    }
                },
            }
        },
    )
    report = provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake board

    assert not any(name == "Status" for _, names in board.patched for name in names)
    told = [what for verb, what in report.steps if verb == "by hand"]
    assert told and "In review" in told[0] and "Blocked" in told[0], told
    assert "Ready" not in told[0], "only what is actually missing"


@case
def a_column_someone_retyped_is_left_alone() -> None:
    board = _Board(
        databases={"root": {"ponos": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Cost": {"rich_text": {}}}},
    )
    provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake board
    assert board._schemas["db-tickets"]["Cost"] == {"rich_text": {}}, "not overruled"


@case
def two_states_on_one_column_produce_one_option() -> None:
    """Notion refuses a select that lists the same option twice."""
    settings = _settings()
    settings.status = {"failed": "Needs you", "blocked": "Needs you"}
    names = [option["name"] for option in provision.status_options(settings)]
    assert names.count("Needs you") == 1
    # Eight: the two that were merged count once, and renaming a failure column
    # says nothing about the validated one, nor the paused or cancelled ones,
    # which keep their defaults.
    assert len(names) == 8 and {"Validated", "Paused", "Cancelled"} <= set(names)

    settings.status = {"review": "Done", "done": "Done"}
    names = [option["name"] for option in provision.status_options(settings)]
    assert names.count("Done") == 1
    assert "Validated" not in names, "a board that ends at the pull request has no gesture"


@case
def the_workspace_is_written_back_into_the_configuration() -> None:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\n# keep me\ntoken = "ntn_x"\nworkspace = ""\n\n[runner]\nfetch = true\n'
    )

    assert C.write_notion_value(path, "workspace", "abc") is True
    assert C.write_notion_value(path, "workspace", "abc") is False, "already says that"

    text = path.read_text()
    assert 'workspace = "abc"' in text
    assert "# keep me" in text, "a hand-edited file keeps its comments"
    assert "[runner]\nfetch = true" in text, "other tables are untouched"
    assert C.load(path).notion.workspace == "abc"


# -- the token init is given -------------------------------------------------


class _Stdin(io.StringIO):
    """stdin as a pipe or as a terminal: what `init` decides on."""

    def __init__(self, text: str, terminal: bool) -> None:
        super().__init__(text)
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal


@contextmanager
def _stdin(text: str, terminal: bool, typed: str = "") -> Iterator[list[str]]:
    """stdin replaced, and `getpass` answering `typed`: yields the prompts it showed."""
    prompts: list[str] = []

    def asked(prompt: str = "") -> str:
        prompts.append(prompt)
        return typed

    name = C.SECRETS[("notion", "token")]
    previous = os.environ.pop(name, None)
    try:
        with (
            mock.patch.object(sys, "stdin", _Stdin(text, terminal)),
            mock.patch.object(getpass, "getpass", asked),
        ):
            yield prompts
    finally:
        os.environ.pop(name, None)
        if previous is not None:
            os.environ[name] = previous


@case
def init_reads_its_token_from_stdin_or_asks_for_it_unechoed() -> None:
    """`--token ntn_…` left the token in the shell's history and in `ps`."""
    from ponos import __main__ as cli

    with _stdin("ntn_piped\n", terminal=False) as prompts:
        assert cli._init_token("-", "") == ("ntn_piped", True)
    assert prompts == [], "a pipe is read, not prompted"

    with _stdin("", terminal=True, typed=" ntn_typed ") as prompts:
        assert cli._init_token("-", "") == ("ntn_typed", True)
    assert len(prompts) == 1, "a terminal asks through getpass, which does not echo"

    with _stdin("", terminal=True, typed="ntn_typed") as prompts:
        assert cli._init_token(None, C.PLACEHOLDER) == ("ntn_typed", True)
    assert len(prompts) == 1, "a bare init in a terminal asks too, when none is set"

    with _stdin("", terminal=True) as prompts:
        assert cli._init_token(None, "ntn_saved") == ("ntn_saved", False)
    assert prompts == [], "one already saved is used as it is"

    with _stdin("", terminal=False) as prompts:
        assert cli._init_token(None, "") == ("", False), "nothing to ask outside a terminal"

    with _stdin("", terminal=False):
        os.environ[C.SECRETS[("notion", "token")]] = "ntn_exported"
        assert cli._init_token(None, "ntn_saved") == ("ntn_exported", True)


@case
def init_with_a_piped_token_hands_it_to_notion_without_printing_it() -> None:
    from ponos import __main__ as cli
    from ponos import notion

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\nworkspace = ""\n')
    given: list[str] = []

    class Client:
        def __init__(self, token: str) -> None:
            given.append(token)

        def page(self, page: str) -> store.Page:
            raise store.StoreError("stopped here")

    printed = io.StringIO()
    with (
        _stdin("ntn_piped\n", terminal=False),
        mock.patch.dict(os.environ, {"PONOS_CONFIG": str(path)}),
        mock.patch.object(notion, "Client", Client),
        contextlib.redirect_stdout(printed),
    ):
        code = cli.main(["init", "https://www.notion.so/Page-" + "a" * 32, "--token", "-"])
    assert code == 1, printed.getvalue()
    assert given == ["ntn_piped"]
    assert "ntn_piped" not in printed.getvalue()


def _init_against(status: int, message: str) -> tuple[int, str]:
    """`ponos init` with a token and a page, Notion answering `status` to the page read."""
    import httpx

    from ponos import __main__ as cli

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\nworkspace = ""\n')
    printed = io.StringIO()
    with (
        _http_answering(lambda request: httpx.Response(status, json={"message": message})),
        _stdin("ntn_faux\n", terminal=False),
        mock.patch.dict(os.environ, {"PONOS_CONFIG": str(path)}),
        contextlib.redirect_stdout(printed),
    ):
        code = cli.main(["init", "https://www.notion.so/Page-" + "a" * 32, "--token", "-"])
    return code, printed.getvalue()


@case
def init_tells_a_refused_token_from_a_page_not_shared() -> None:
    code, said = _init_against(401, "API token is invalid.")
    assert code == 1, said
    assert "notion.so/profile/integrations" in said, said
    assert "Connections" not in said, "a wrong token is not cured by sharing the page"

    code, said = _init_against(404, "Could not find page with ID")
    assert code == 1, said
    assert "Connections" in said, said
    assert "profile/integrations" not in said, said


@case
def the_wizard_tells_a_refused_token_from_a_page_not_shared() -> None:
    import httpx

    from ponos import notion
    from ponos.web import setup

    for status, expected in ((401, "profile/integrations"), (404, "Connections")):

        def refusing(request: httpx.Request, status: int = status) -> httpx.Response:
            return httpx.Response(status, json={"message": "x"})

        with _http_answering(refusing):
            try:
                notion.Client("ntn_faux").page("a" * 32)
            except store.StoreError as error:
                said = setup.notion_problem(error)
        assert expected in said, said
