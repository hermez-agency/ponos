"""A project's picture, kept on this machine and kept in step with the board.

A project page already has two pictures, and Notion's own: the **cover**, the
banner across the top of the page, and the **icon**, the emoji or small image in
front of its title. Those are what the console shows — a thumbnail in the list,
a banner on the page — rather than a `Files` column added for the purpose: the
pictures people have already chosen for their pages are then the ones they see,
and a picture changed in either place is changed in both without a column to
keep in step with a cover.

Three things make that harder than showing a URL.

**A file Notion hosts is behind a URL that expires within the hour.** Handed to
a browser, it works on Monday morning and is a broken image by lunch. So no such
URL leaves this module: what the console is given is its own address,
`/api/projects/<id>/image/cover`, and what answers it is a copy on disk under
the state directory. The copy is fetched again when it can no longer be trusted
— the page was edited since, or the picture is another one — and a URL whose
hour is up is never tried: the page is read again for a fresh one.

**A picture changed here has to reach Notion, and may not.** The network is
down, the integration may not update pages. What was chosen is then kept as a
*pending* change, shown here as if it had landed, and sent again at the next
reading of the board. Nothing is lost, and nothing is shown that was not asked.

**A change comes back.** What the console writes, Notion answers with, and the
next reading of the board finds it again. Taken for somebody else's change, it
would be downloaded again — or, worse, a pending change would be settled
against itself. So a picture is *agreed* on, the way `sync.py` stamps a page:
what the board said last time we agreed, by an identity that does not change
with each signature Notion puts on a URL. A reading that finds the agreed
picture finds nothing new; only a reading that finds another one has seen
somebody move. And the page the board answers a write with is agreed on at
once, so a change is never read back as news.

When both moved between two readings — a change is still pending here, and the
page shows another picture than the one agreed — the newest wins, as in
`storage.conflict = "newest"`: the pending change's own time against the
page's `last_edited_time`. Which side won is kept, and the console says it.
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import db, http
from .store import SLOTS, Page, Picture, StoreError

# What one picture may weigh, downloaded or uploaded: Notion's own ceiling for
# a file sent in one piece, and far more than any banner needs.
LIMIT = 20 * 1024 * 1024

# How long before its stated end a Notion URL is already treated as gone: a
# download that starts in the last seconds of the hour does not finish in it.
MARGIN = timedelta(minutes=5)

# How a picture is named on disk, by what it is. SVG is kept — Notion's own
# icons are SVG — and served under a policy that lets it draw and never run.
SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
}

Push = Callable[[str, Picture], Page]


def root() -> Path:
    from .config import state_dir

    return state_dir() / "images"


@dataclass
class Face:
    """One picture as the board shows it, reduced to what this module needs.

    `kind` is `emoji`, `file` (Notion keeps it, behind a URL that expires),
    `external` (somebody else keeps it), `local` (a file beside a Markdown
    page), or empty for no picture at all. `identity` is what stays the same
    for as long as the picture does.
    """

    kind: str = ""
    url: str = ""
    emoji: str = ""
    expires: str = ""
    identity: str = ""


def face(raw: dict[str, Any], slot: str) -> Face:
    """The cover or the icon of a page, in any of the shapes Notion hands over.

    A Notion-hosted file is known by its URL without the query string: the
    signature changes on every read, the file it signs does not.
    """
    value = raw.get(slot) or {}
    kind = value.get("type", "")
    if kind == "emoji" and value.get("emoji"):
        return Face("emoji", emoji=value["emoji"], identity=f"emoji:{value['emoji']}")
    if kind == "file":
        inner = value.get("file") or {}
        url = str(inner.get("url", ""))
        return Face(
            "file",
            url=url,
            expires=str(inner.get("expiry_time") or ""),
            identity=f"file:{url.split('?', 1)[0]}",
        )
    if kind in ("external", "custom_emoji"):
        url = str((value.get(kind) or {}).get("url", ""))
        if not url:
            return Face()
        if url.startswith("file:"):
            return Face("local", url=url, identity=f"local:{url}")
        return Face("external", url=url, identity=f"external:{url}")
    if kind == "file_upload":
        # Attached a moment ago and not yet turned into a file by Notion: the
        # upload's ID is all there is, and it is enough to recognise it.
        upload = str((value.get("file_upload") or {}).get("id", ""))
        return Face("file", identity=f"upload:{upload}")
    return Face()


def download(url: str) -> tuple[bytes, str]:
    """The picture at that URL, and what it is. Raises StoreError."""
    where = urllib.parse.urlsplit(url).netloc or url[:60]
    try:
        answer = http.send("images", "GET", url, timeout=20, limit=LIMIT)
    except http.Unanswered as error:
        raise StoreError(f"the picture at {where} could not be fetched: {error}") from error
    if answer.status >= 400:
        raise StoreError(f"{where} answered {answer.status} for the picture")
    declared, data = answer.kind, answer.body
    if len(data) > LIMIT:
        raise StoreError(f"the picture at {where} is larger than {LIMIT // (1024 * 1024)} MB")
    kind = sniff(data, declared)
    if not kind:
        raise StoreError(f"what {where} answered is not a picture ({declared})")
    return data, kind


def sniff(data: bytes, declared: str = "") -> str:
    """What those bytes are, when they are a picture this module keeps.

    What the server said first, when it is one of them; the first bytes
    otherwise — a bucket that serves everything as `octet-stream` is common.
    """
    declared = declared.split(";")[0].strip().lower()
    if declared in SUFFIXES:
        return declared
    head = data[:64]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    text = head.lstrip().lower()
    if text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in data[:1024].lower()):
        return "image/svg+xml"
    return ""


def _moment(stamp: str) -> datetime:
    """An ISO timestamp, comparable. Anything unreadable is the beginning of time."""
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _edited(page: Page) -> str:
    return str(page.raw.get("last_edited_time") or page.raw.get("created_time") or "")


class Cache:
    """The pictures of every project page, on disk, and what was agreed on them.

    One entry per page and slot, in the `images` table of `ponos.db` (which
    replaced `index.json`); the pictures themselves in `directory`. An entry holds what the board showed when we last agreed (`agreed`, and
    where to fetch it), the copy on disk, and — while one is waiting — the
    change the console made that the board has not taken yet.

    The console's server answers requests on several threads at once, so an
    entry is worked on as a copy under that page's own lock and put back whole:
    one project's slow upload never holds up another's thumbnail.
    """

    def __init__(
        self,
        directory: Path,
        *,
        fetch: Callable[[str], tuple[bytes, str]] = download,
        clock: Callable[[], datetime] | None = None,
        database: Path | None = None,
    ) -> None:
        self._dir = Path(directory)
        self._database = database
        self._fetch = fetch
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._known: dict[str, dict] | None = None

    # -- the index -----------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self._dir

    def _index(self) -> dict[str, dict]:
        if self._known is None:
            try:
                with db.transaction(immediate=False, location=self._database) as connection:
                    rows = connection.execute("SELECT key, entry FROM images").fetchall()
                self._known = {str(key): json.loads(entry) for key, entry in rows}
            except (*db.ERRORS, json.JSONDecodeError):
                self._known = {}
        return self._known

    def _key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(key, threading.Lock())

    def entry(self, page_id: str, slot: str) -> dict:
        """A copy of what is known of one picture. Changing it changes nothing."""
        with self._lock:
            return json.loads(json.dumps(self._index().get(_key(page_id, slot), {})))

    def _commit(self, key: str, entry: dict) -> None:
        with self._lock:
            known = self._index()
            if known.get(key) == entry:
                return
            known[key] = entry
            # A signed URL is kept in memory for the hour it is good for, and
            # never written down: on disk it would only ever be a dead one, and
            # a process started later asks the page for a fresh one anyway.
            written = {**entry, "url": ""} if entry.get("kind") == "file" else entry
            try:
                with db.transaction(location=self._database) as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO images (key, entry) VALUES (?, ?)",
                        (key, json.dumps(written, ensure_ascii=False)),
                    )
            except db.ERRORS:
                pass  # kept in memory: the next change to it writes it again

    # -- reading the board ---------------------------------------------------

    def observe(self, page: Page, push: Push) -> None:
        """What one reading of the board says about a page's pictures.

        Called on every page of the projects database each time it is read —
        which is the synchronisation: a change somebody made in Notion is
        agreed on, a change of ours still waiting is sent again, and when both
        happened since the last reading, the newest wins.
        """
        page_id = _bare(page.id)
        for slot in SLOTS:
            key = _key(page_id, slot)
            with self._key_lock(key):
                entry = self.entry(page_id, slot)
                self._settle(entry, face(page.raw, slot), _edited(page), slot, push)
                self._commit(key, entry)

    def _settle(self, entry: dict, seen: Face, edited: str, slot: str, push: Push) -> None:
        pending = entry.get("pending")
        moved = "agreed" in entry and entry["agreed"] != seen.identity
        if pending:
            if moved:
                ours = pending.get("at", "")
                console = _moment(ours) > _moment(edited)
                entry["conflict"] = {
                    "winner": "console" if console else "notion",
                    "console": ours,
                    "notion": edited,
                }
                if not console:
                    self._drop(entry)
                    self._agree(entry, seen, edited)
                    return
            self._push(entry, slot, push)
            return
        if moved or "agreed" not in entry:
            self._agree(entry, seen, edited)
            return
        # The same picture. Its URL is a fresh one, worth keeping for the next
        # download; and a page edited since the copy was made may have been
        # given another image under the same name, so the copy is fetched again.
        entry["url"], entry["expires"] = seen.url, seen.expires
        if entry.get("edited") != edited:
            entry["edited"] = edited
            entry["stale"] = True

    def _agree(self, entry: dict, seen: Face, edited: str) -> None:
        """Take what the board shows as the picture, forgetting a copy of another."""
        if entry.get("agreed") != seen.identity:
            self._forget_file(entry.get("file", ""))
            entry["file"] = ""
            entry["type"] = ""
        entry.update(
            agreed=seen.identity,
            kind=seen.kind,
            url=seen.url,
            emoji=seen.emoji,
            expires=seen.expires,
            edited=edited,
            stale=False,
        )

    def _drop(self, entry: dict) -> None:
        pending = entry.pop("pending", None) or {}
        if pending.get("file") and pending["file"] != entry.get("file"):
            self._forget_file(pending["file"])
        entry.pop("error", None)

    def _push(self, entry: dict, slot: str, push: Push) -> bool:
        """Send the pending change to the board, and agree on what it answers."""
        pending = entry.get("pending") or {}
        picture = Picture(
            url=pending.get("url", ""),
            emoji=pending.get("emoji", ""),
            type=pending.get("type", ""),
            name=pending.get("name", ""),
        )
        if pending.get("file"):
            try:
                picture.data = (self._dir / pending["file"]).read_bytes()
            except OSError:
                # The copy it was made of is gone: nothing left to send.
                self._drop(entry)
                return False
        try:
            answer = push(slot, picture)
        except StoreError as error:
            entry["error"] = str(error).splitlines()[0] if str(error) else type(error).__name__
            entry["tried"] = self._clock().isoformat(timespec="seconds")
            return False
        # What we sent is what the board now shows: agreed on at once, so that
        # the next reading finds nothing new — and the bytes we uploaded are the
        # copy, with no reason to download them back.
        mine = pending.get("file", "")
        self._agree(entry, face(answer.raw, slot), _edited(answer))
        if mine:
            if entry.get("file") not in ("", mine):
                self._forget_file(entry["file"])
            entry["file"], entry["type"] = mine, pending.get("type", "")
        entry.pop("pending", None)
        entry.pop("error", None)
        entry.pop("tried", None)
        return True

    # -- the console's own changes -------------------------------------------

    def change(self, page_id: str, slot: str, picture: Picture, push: Push) -> dict:
        """Make that the picture: here at once, and on the board if it answers.

        What the board refuses stays pending — shown here, and sent again at the
        next reading. Returns the entry as it now stands.
        """
        if slot not in SLOTS:
            raise ValueError(f"no such picture on a page: {slot}")
        page_id = _bare(page_id)
        key = _key(page_id, slot)
        with self._key_lock(key):
            entry = self.entry(page_id, slot)
            self._drop(entry)
            entry.pop("conflict", None)
            pending: dict[str, Any] = {"at": self._clock().isoformat(timespec="microseconds")}
            if picture.data:
                kind = sniff(picture.data, picture.type)
                if not kind:
                    raise ValueError("that file is not a picture")
                name = f"{_digest(key)}-{_digest(pending['at'])}{SUFFIXES[kind]}"
                try:
                    self._dir.mkdir(parents=True, exist_ok=True)
                    (self._dir / name).write_bytes(picture.data)
                except OSError as error:
                    raise StoreError(f"{self._dir}: {error}") from error
                pending.update(
                    kind="upload",
                    file=name,
                    type=kind,
                    name=picture.name or f"{slot}{SUFFIXES[kind]}",
                )
            elif picture.url:
                scheme = urllib.parse.urlsplit(picture.url).scheme
                if scheme not in ("http", "https"):
                    raise ValueError("a picture's address starts with https://")
                pending.update(kind="external", url=picture.url)
            elif picture.emoji:
                if slot != "icon":
                    raise ValueError("a cover is an image, not an emoji")
                pending.update(kind="emoji", emoji=picture.emoji)
            else:
                pending.update(kind="remove")
            entry["pending"] = pending
            self._push(entry, slot, push)
            self._commit(key, entry)
            return entry

    # -- what the console is shown -------------------------------------------

    def shown(self, page_id: str, slot: str) -> dict[str, Any]:
        """One picture, as the console draws it — never a URL of Notion's.

        `version` changes whenever the picture may have, which is what the
        console puts in the address of the image so that a browser that kept
        the old one asks again.
        """
        entry = self.entry(page_id, slot)
        pending = entry.get("pending")
        kind = (pending or {}).get("kind") or entry.get("kind", "")
        said: dict[str, Any] = {"kind": ""}
        if kind in ("upload", "file", "external", "local"):
            said["kind"] = "image"
            version = f"{entry.get('agreed')}|{entry.get('edited')}|{(pending or {}).get('at', '')}"
            if kind == "local":
                try:
                    version += str(_path(entry.get("url", "")).stat().st_mtime_ns)
                except OSError:
                    pass
            said["version"] = _digest(version)
            url = (pending or {}).get("url") or entry.get("url", "")
            if kind == "external" and url:
                said["url"] = url
        elif kind == "emoji":
            said["kind"] = "emoji"
            said["emoji"] = (pending or {}).get("emoji") or entry.get("emoji", "")
        if pending:
            said["pending"] = True
        if entry.get("error"):
            said["error"] = entry["error"]
        if entry.get("conflict"):
            said["conflict"] = entry["conflict"].get("winner", "")
        return said

    def picture(self, page_id: str, slot: str, reread: Callable[[], Page]) -> tuple[bytes, str]:
        """The bytes of one picture, from the copy when it can be trusted.

        `reread` asks the board for the page again, which is what an expired
        URL costs: the page is the only thing that hands out a fresh one.
        Raises LookupError when there is no picture to give, and StoreError
        when there is one that could not be fetched and no copy to fall back on.
        """
        page_id = _bare(page_id)
        key = _key(page_id, slot)
        with self._key_lock(key):
            entry = self.entry(page_id, slot)
            pending = entry.get("pending") or {}
            if pending.get("file"):
                return self._read(pending["file"], pending.get("type", ""))
            if pending.get("kind") == "external":
                return self._fetch(pending["url"])
            if pending:
                raise LookupError(f"no image for the {slot} of {page_id}")
            kind = entry.get("kind", "")
            if kind == "local":
                path = _path(entry.get("url", ""))
                if path.suffix.lower() not in SUFFIXES.values():
                    raise LookupError(f"{path.name} is not a picture")
                try:
                    data = path.read_bytes()
                except OSError as error:
                    raise LookupError(f"{path}: {error.strerror or error}") from error
                return data, sniff(data) or "application/octet-stream"
            if kind not in ("file", "external"):
                raise LookupError(f"no image for the {slot} of {page_id}")
            if entry.get("file") and not entry.get("stale"):
                try:
                    return self._read(entry["file"], entry.get("type", ""))
                except OSError:
                    pass
            try:
                data, kind_of = self._download(entry, slot, reread)
            except StoreError:
                # The old copy, if there is one, is better than no picture: it
                # is what was shown until a moment ago.
                if entry.get("file"):
                    try:
                        return self._read(entry["file"], entry.get("type", ""))
                    except OSError:
                        pass
                raise
            name = f"{_digest(key)}{SUFFIXES.get(kind_of, '')}"
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                (self._dir / name).write_bytes(data)
            except OSError:
                return data, kind_of  # served, just not kept
            if entry.get("file") and entry["file"] != name:
                self._forget_file(entry["file"])
            entry.update(file=name, type=kind_of, stale=False)
            self._commit(key, entry)
            return data, kind_of

    def _download(self, entry: dict, slot: str, reread: Callable[[], Page]) -> tuple[bytes, str]:
        """Fetch the agreed picture, asking the page for a new URL if its hour is up."""
        url = entry.get("url", "")
        expires = entry.get("expires", "")
        if entry.get("kind") == "file" and (
            not url or (expires and _moment(expires) - MARGIN <= self._clock())
        ):
            page = reread()
            seen = face(page.raw, slot)
            if seen.identity != entry.get("agreed"):
                # Changed in Notion since the last reading: that is the picture now.
                self._agree(entry, seen, _edited(page))
            entry["url"], entry["expires"] = seen.url, seen.expires
            url = seen.url
            if not url:
                raise StoreError(f"Notion gave no address for the {slot}")
        return self._fetch(url)

    def _read(self, name: str, kind: str) -> tuple[bytes, str]:
        data = (self._dir / name).read_bytes()
        return data, kind or sniff(data) or "application/octet-stream"

    def _forget_file(self, name: str) -> None:
        if name:
            try:
                (self._dir / name).unlink(missing_ok=True)
            except OSError:
                pass


def _key(page_id: str, slot: str) -> str:
    return f"{_bare(page_id)}:{slot}"


def _bare(identifier: str) -> str:
    return str(identifier or "").replace("-", "").strip()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _path(url: str) -> Path:
    return Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path))
