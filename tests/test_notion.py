"""`notion.py`: what is sent to Notion, how, and how it is read back."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import httpx
from support import _http_answering, case

from ponos import config as C
from ponos import http as http_module
from ponos import notion
from ponos.__main__ import main as cli_main

# -- Notion encoding ---------------------------------------------------------


@contextmanager
def _notion_answering(*answers):
    """Notion's transport replaced by a script: each call takes the next answer.

    An answer is a dict (the JSON Notion returns), an `httpx.Response`, or an
    exception to raise, the way httpx raises it. Yields the calls made, as
    (method, path), and the pauses taken between them.
    """
    calls: list[tuple[str, str]] = []
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url).split("/v1", 1)[-1]))
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    with _http_answering(handler) as pauses:
        yield calls, pauses


def _http_error(code: int, retry_after: str = ""):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(code, headers=headers, json={"message": f"status {code}"})


@case
def the_console_starts_on_the_file_install_sh_leaves(state_home):
    """`serve` used to require a usable configuration, and exit 2 without a
    Notion token — so the console whose first connection *asks* for that token
    could not be reached, and its unit restarted in a loop on a fresh install.

    It starts now; the board it cannot read yet says why without asking Notion,
    and `run` — the timer's command — still refuses, out loud.
    """
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    with tempfile.TemporaryDirectory() as directory:
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

    def refuse(request):
        raise AssertionError("the placeholder token was sent to Notion")

    with _http_answering(refuse):
        for token in ("", C.PLACEHOLDER):
            try:
                notion.Client(token)._request("POST", "/databases/d/query", {})
            except notion.NotionError as error:
                assert "no Notion token yet" in str(error)
            else:
                raise AssertionError("a board with no token was read")


@case
def a_read_that_times_out_is_asked_again_and_says_notion_when_it_gives_up():
    """A timeout or a reset while reading used to escape as a bare OSError.

    Nothing catches an OSError around a Notion call — `StoreError` is what the
    runner is written to survive — so one slow answer took the whole pass down.
    """
    client = notion.Client("ntn_x")
    with _notion_answering(
        httpx.ReadTimeout("timed out"), httpx.ReadError("reset"), {"object": "page", "id": "p"}
    ) as (calls, pauses):
        assert client._request("GET", "/pages/p") == {"object": "page", "id": "p"}
    assert len(calls) == 3 and len(pauses) == 2, (calls, pauses)

    with _notion_answering(*[httpx.ReadTimeout("timed out")] * notion.MAX_ATTEMPTS) as (calls, _):
        try:
            client._request("POST", "/databases/d/query", {})
        except notion.NotionError as error:
            assert "gave up" in str(error), error
        else:
            raise AssertionError("a Notion that never answers was taken for an answer")
    assert len(calls) == notion.MAX_ATTEMPTS, "a query is a read, and is retried"

    refused = httpx.ConnectError("[Errno 111] Connection refused")
    with _notion_answering(refused, {"results": []}) as (calls, _):
        assert client._request("GET", "/users/me") == {"results": []}


@case
def a_comment_is_never_posted_twice_on_the_strength_of_a_silence():
    """A write that may have landed is not sent again: a duplicate comment is
    worse than an error. Only what Notion refused outright — a 429, or a
    connection that never carried the request — is safe to send twice."""
    client = notion.Client("ntn_x")
    for silence in (
        httpx.ReadTimeout("timed out"),
        httpx.ReadError("reset"),
        _http_error(502),
    ):
        with _notion_answering(silence, {"object": "comment"}) as (calls, _):
            try:
                client._request("POST", "/comments", {"rich_text": []})
            except notion.NotionError:
                pass
            else:
                raise AssertionError(f"{silence!r} was retried on a write")
        assert calls == [("POST", "/comments")], (silence, calls)

    refused = httpx.ConnectError("[Errno 111] Connection refused")
    with _notion_answering(refused, {"object": "comment"}) as (calls, _):
        assert client._request("POST", "/comments", {}) == {"object": "comment"}
    assert len(calls) == 2, "never sent is safe to send"

    with _notion_answering(_http_error(429, retry_after="7"), {"object": "comment"}) as (
        calls,
        pauses,
    ):
        assert client._request("POST", "/comments", {}) == {"object": "comment"}
    assert len(calls) == 2 and pauses == [7.0], (calls, pauses)

    with _notion_answering(_http_error(429, retry_after="86400"), {}) as (_, pauses):
        client._request("GET", "/users/me")
    assert pauses == [http_module.LONGEST_WAIT], "a day is not a pause, it is a refusal"

    with _notion_answering(httpx.ReadTimeout("timed out"), {}) as (calls, _):
        try:
            client._request("PATCH", "/blocks/b/children", {"children": []})
        except notion.NotionError:
            pass
    assert len(calls) == 1, "appending blocks twice is two copies of them"

    with _notion_answering(_http_error(503), {"id": "p"}) as (calls, _):
        client._request("PATCH", "/pages/p", {"properties": {}})
    assert len(calls) == 2, "setting a value twice is setting it once"


@case
def an_append_refused_halfway_takes_back_what_it_had_written():
    """Notion takes a hundred blocks at a time: an answer longer than that was
    two requests, and a refusal on the second left the first on the page. The
    ticket failed, the next session wrote its answer whole after it — and the
    page read as a cut answer followed by the full one.

    What the batches before the refusal created is deleted again, and the error
    still says the answer was not written.
    """
    client = notion.Client("ntn_x")
    blocks = [{"type": "paragraph", "paragraph": {"rich_text": []}}] * 150
    written = {"results": [{"id": f"b{index}"} for index in range(100)]}
    deleted = [{"object": "block"}] * 100
    with _notion_answering(written, _http_error(400), *deleted) as (calls, _):
        try:
            client.append_blocks("p", blocks)
        except notion.NotionError:
            pass
        else:
            raise AssertionError("a refused batch was taken for a written one")
    assert calls[:2] == [("PATCH", "/blocks/p/children")] * 2, calls
    assert calls[2:] == [("DELETE", f"/blocks/b{index}") for index in range(100)], calls[2:5]


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
    assert notion._encode("status", "") is None, "a status cannot be emptied, so it is left"


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
        id="x",
        url="u",
        title="t",
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
