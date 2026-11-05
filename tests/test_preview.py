"""`preview.py`: the captures taken before and after, and the processes left behind (none)."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

from support import case

from ponos import preview, project_settings

# Writes a PNG-looking file where `--screenshot=` says, as Chrome would.
CHROME = """#!/bin/sh
for argument in "$@"; do
  case "$argument" in --screenshot=*) printf 'png' > "${argument#--screenshot=}";; esac
done
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _with_chrome() -> str:
    folder = Path(tempfile.mkdtemp())
    (folder / "google-chrome").write_text(CHROME, encoding="utf-8")
    (folder / "google-chrome").chmod(0o755)
    previous = os.environ["PATH"]
    os.environ["PATH"] = f"{folder}{os.pathsep}{previous}"
    return previous


@case
def a_preview_is_read_whole_or_not_at_all() -> None:
    assert not preview.parse(None) and not preview.parse({"command": "x"})
    assert not preview.parse({"command": "x", "url": "ftp://host"}), "only http(s)"
    read = preview.parse({"command": " npm run dev ", "url": "http://127.0.0.1:5173/", "pages": []})
    assert read.command == "npm run dev" and read.url == "http://127.0.0.1:5173", read
    assert read.pages == ("/",), "no page listed is the home page"
    many = preview.parse(
        {"command": "x", "url": "http://h:1", "pages": ["/a", " ", 3, *("/b",) * 10]}
    )
    assert many.pages[0] == "/a" and len(many.pages) == preview.MAX_PAGES, many


@case
def a_project_keeps_its_preview_and_forgets_it(state_home: Path) -> None:
    setting = preview.parse({"command": "make dev", "url": "http://h:1", "pages": ["/", "/x"]})
    project_settings.set_preview("aaaa-bbbb", "Demo", setting)
    assert project_settings.preview("aaaabbbb") == setting
    project_settings.set_preview("aaaa-bbbb", "Demo", preview.Setting())
    assert not project_settings.preview("aaaabbbb")
    assert not project_settings.preview("")


@case
def the_server_is_photographed_then_killed_with_everything_it_started(state_home: Path) -> None:
    port = _free_port()
    # A shell that starts a server in a child: only the process group reaches it.
    command = f"{sys.executable} -m http.server {port} --bind 127.0.0.1 & wait"
    setting = preview.Setting(command, f"http://127.0.0.1:{port}", ("/", "/other"))
    workdir = Path(tempfile.mkdtemp())
    out = Path(tempfile.mkdtemp())
    previous = _with_chrome()
    try:
        files, skipped = preview.shoot(setting, workdir, out, "after", log=out / "log")
    finally:
        os.environ["PATH"] = previous
    assert not skipped and [f.name for f in files] == ["after-0.png", "after-1.png"], (
        files,
        skipped,
    )
    assert not preview._answers(setting.url), "nothing keeps answering after the pass"


@case
def an_address_that_already_answers_is_never_photographed(state_home: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        url = f"http://127.0.0.1:{busy.getsockname()[1]}"
        previous = _with_chrome()
        try:
            out = Path(tempfile.mkdtemp())
            files, skipped = preview.shoot(
                preview.Setting("true", url), out, out, "after", log=out / "log"
            )
        finally:
            os.environ["PATH"] = previous
    assert not files and "already answers" in skipped, skipped


@case
def a_server_that_stops_at_once_is_said(state_home: Path) -> None:
    out = Path(tempfile.mkdtemp())
    previous = _with_chrome()
    try:
        files, skipped = preview.shoot(
            preview.Setting("exit 3", f"http://127.0.0.1:{_free_port()}"),
            out,
            out,
            "after",
            log=out / "log",
        )
    finally:
        os.environ["PATH"] = previous
    assert not files and "exit 3" in skipped, skipped


@case
def the_captures_of_a_ticket_are_listed_in_page_order_and_read_by_name(state_home: Path) -> None:
    folder = preview.folder("1234-5678")
    preview.write_pages(folder, preview.Setting("c", "http://h:1", ("/", "/settings")))
    for side in preview.SIDES:
        for number in (0, 1):
            (folder / f"{side}-{number}.png").write_bytes(b"png")
    shots = preview.listing("12345678")
    assert [(s["side"], s["page"]) for s in shots] == [
        ("before", "/"),
        ("before", "/settings"),
        ("after", "/"),
        ("after", "/settings"),
    ], shots
    assert preview.read("12345678", "after-1.png") == b"png"
    assert preview.read("12345678", "../after-1.png") is None
    assert preview.read("12345678", "pages.txt") is None
    assert preview.listing("nothing") == []


@case
def the_pictures_go_to_origin_alone_and_leave_the_branch_untouched() -> None:
    from ponos import git

    with tempfile.TemporaryDirectory() as home:
        origin, repo = Path(home) / "origin.git", Path(home) / "repo"
        assert git.git(["init", "-q", "--bare", "-b", "main", str(origin)], home).ok
        assert git.git(["clone", "-q", str(origin), str(repo)], home).ok
        for step in (
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
            ["commit", "-q", "--allow-empty", "-m", "first"],
        ):
            assert git.git(step, repo).ok, step
        head = git.head(repo)
        shots = Path(home) / "shots"
        shots.mkdir()
        (shots / "before-0.png").write_bytes(b"one")
        (shots / "after-0.png").write_bytes(b"two")
        files = [shots / "before-0.png", shots / "after-0.png"]
        pushed = git.push_pictures(repo, "previews/abcd1234", files)
        assert pushed, "the commit is said"
        assert git.git(["rev-parse", "refs/ponos/previews/abcd1234"], origin).out == pushed
        listed = git.git(["ls-tree", "--name-only", pushed], origin).out.split()
        assert sorted(listed) == ["after-0.png", "before-0.png"], listed
        assert git.git(["show", f"{pushed}:after-0.png"], origin).out == "two"
        assert git.head(repo) == head and not git.is_dirty(repo), "the branch is as it was"
        assert not git.git(["rev-parse", "--verify", "--quiet", f"{pushed}^"], origin).ok
        (shots / "after-0.png").write_bytes(b"three")
        again = git.push_pictures(repo, "previews/abcd1234", files)
        assert again and again != pushed, "the same name pushed again replaces it"
        assert git.git(["rev-parse", "refs/ponos/previews/abcd1234"], origin).out == again


@case
def the_comment_shows_each_page_before_and_after_or_names_the_file() -> None:
    from ponos.voice import Voice

    shots = [
        {"side": "before", "page": "/", "file": "before-0.png"},
        {"side": "before", "page": "/settings", "file": "before-1.png"},
        {"side": "after", "page": "/", "file": "after-0.png"},
    ]
    body = Voice("en").previews_comment(shots, lambda name: f"https://x/{name}")
    lines = body.splitlines()
    assert "| `/` | ![before](https://x/before-0.png) | ![after](https://x/after-0.png) |" in lines
    assert "| `/settings` | ![before](https://x/before-1.png) | — |" in lines, body
    named = Voice("en").previews_comment(shots, lambda name: "")
    assert "| `/` | before-0.png | after-0.png |" in named.splitlines(), named
