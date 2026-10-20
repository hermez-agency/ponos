"""`images.py`: a project's picture."""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import ROOT, _board, _markdown_api, case

from ponos import db, files, images, notion, store

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
        id=page_id,
        url="",
        title="Opoil",
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
        self.now = datetime(2026, 9, 30, 8, 5, tzinfo=UTC)
        self.fetched: list[str] = []
        self.answer = fetched
        self.directory = Path(tempfile.mkdtemp())
        self.cache = images.Cache(
            self.directory,
            fetch=self._fetch,
            clock=lambda: self.now,
            database=self.directory / "ponos.db",
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
    before = _project_page(
        cover=_notion_file("w/f/old.png", "a"), edited="2026-09-30T08:00:00.000Z"
    )

    def refuse(slot: str, picture: store.Picture) -> notion.Page:
        raise notion.NotionError("urlopen error [Errno -3] Temporary failure in name resolution")

    # Chosen here at 08:05, changed in Notion at 08:30: Notion's is the newer.
    with _pictures() as pictures:
        pictures.cache.observe(before, _never)
        pictures.cache.change(
            before.id, "cover", store.Picture(url="https://example.org/a.jpg"), refuse
        )
        theirs = _project_page(
            cover=_notion_file("w/f/theirs.png", "b"), edited="2026-09-30T08:30:00.000Z"
        )
        pictures.cache.observe(theirs, _never)
        shown = pictures.cache.shown(before.id, "cover")
        assert shown["conflict"] == "notion" and "pending" not in shown, shown
        assert pictures.cache.entry(before.id, "cover")["agreed"].endswith("theirs.png")

    # Changed in Notion at 08:02, chosen here at 08:05: the console's is the newer.
    with _pictures() as pictures:
        pictures.cache.observe(before, _never)
        pictures.cache.change(
            before.id, "cover", store.Picture(url="https://example.org/a.jpg"), refuse
        )
        theirs = _project_page(
            cover=_notion_file("w/f/theirs.png", "b"), edited="2026-09-30T08:02:00.000Z"
        )
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
    page = client.set_picture(
        "b" * 32, "cover", store.Picture(data=PNG, type="image/png", name="opoil.png")
    )
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
