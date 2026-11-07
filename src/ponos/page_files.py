"""The files a page carried in Notion, kept beside `ponos.db` once Notion is let go.

**A page names a file by its block, and that is kept.** `markdown.attached`
writes « image attached to the ticket: … (Notion block <id>) » and the console
draws it from `/api/files/<block>`. The import (`notion_import.py`) leaves those
lines as they are and keeps the file under the same block id: nothing in a text
has to be rewritten, and a text imported before the file was fetched is whole
the day it is.

**Kept by what it is, served by what we say it is.** The extension decides the
type the file is sent back as, from the list below; anything else (a page, an
SVG, a script) is stored as `.bin` and sent as a download. Files are resent
from the console's own origin, so a document that a browser would run is never
one of them — the rule `web/attachments.py` gives for the same reason.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from pathlib import Path

from . import db, disk, http
from .log import FILE_ONLY
from .store import StoreError

log = logging.getLogger(__name__)

# Most of a page's files are screenshots; a PDF or a video is the rest.
LIMIT = 100 * 1024 * 1024

TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "avif": "image/avif",
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
}
_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/json": "json",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}
_BLOCK = re.compile(r"\(Notion block ([0-9a-f]{32})\)\]")
_NAME = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{1,5}")


class Gone(StoreError):
    """The file is not there any more, for anybody: a dead link, a block without a file."""


def directory() -> Path:
    return db.path().parent / "page-files"


def blocks(text: str) -> list[str]:
    """The blocks a text names a file by, in order, once each."""
    return list(dict.fromkeys(_BLOCK.findall(text)))


def find(block: str) -> Path | None:
    """The file kept for that block, or None."""
    name = block.replace("-", "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", name):
        return None
    for path in directory().glob(f"{name}.*"):
        if path.suffix != ".gone" and _NAME.fullmatch(path.name):
            return path
    return None


def gone(block: str) -> str:
    """Why that block's file could not be had, when it never will be; empty otherwise."""
    marker = directory() / f"{block.replace('-', '').lower()}.gone"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def lost(block: str, reason: str) -> None:
    """Write down that a block's file is gone at its source, so that it is not asked for again."""
    folder = directory()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        disk.private_dir(folder)
        disk.write_private(folder / f"{block.replace('-', '').lower()}.gone", reason)
    except OSError:
        log.warning("could not note the loss of %s", block, exc_info=True, extra=FILE_ONLY)


def served_as(path: Path) -> tuple[str, bool]:
    """(type, shown inline) for a kept file: only what a browser cannot run is shown."""
    kind = TYPES.get(path.suffix.lstrip("."))
    return (kind, True) if kind else ("application/octet-stream", False)


def keep(block: str, url: str) -> Path:
    """Fetch the file at `url` and keep it as the block's. Raises StoreError."""
    existing = find(block)
    if existing is not None:
        return existing
    where = urllib.parse.urlsplit(url).netloc or url[:60]
    try:
        answer = http.send("page-files", "GET", url, timeout=60, limit=LIMIT)
    except http.Unanswered as error:
        raise StoreError(f"the file at {where} could not be fetched: {error}") from error
    if answer.status in (404, 410):
        raise Gone(f"{where} answered {answer.status} for a file")
    if answer.status >= 400:
        raise StoreError(f"{where} answered {answer.status} for a file")
    if len(answer.body) > LIMIT:
        raise StoreError(f"the file at {where} is larger than {LIMIT // (1024 * 1024)} MB")
    suffix = urllib.parse.unquote(urllib.parse.urlsplit(url).path).rsplit(".", 1)[-1].lower()
    extension = _BY_TYPE.get(answer.kind) or (suffix if suffix in TYPES else "bin")
    folder = directory()
    target = folder / f"{block.replace('-', '').lower()}.{extension}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        disk.private_dir(folder)
        scratch = target.with_name(f".{target.name}.part")
        scratch.write_bytes(answer.body)
        scratch.chmod(disk.PRIVATE)
        scratch.replace(target)
    except OSError as error:
        log.warning("could not keep %s", target, exc_info=True, extra=FILE_ONLY)
        raise StoreError(f"{target}: {error}") from error
    return target
