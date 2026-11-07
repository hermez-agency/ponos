"""The files the pages carried, kept beside `ponos.db` under `page-files/`.

**A page names a file by its block, and that is kept.** The console draws it
from `/api/files/<block>`: the file is the one whose name is that block's id.

**Kept by what it is, served by what we say it is.** The extension decides the
type the file is sent back as, from the list below; anything else (a page, an
SVG, a script) is sent as a download. Files are resent from the console's own
origin, so a document that a browser would run is never one of them — the rule
`web/attachments.py` gives for the same reason.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import db

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
_NAME = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{1,5}")


def directory() -> Path:
    return db.path().parent / "page-files"


def find(block: str) -> Path | None:
    """The file kept for that block, or None."""
    name = block.replace("-", "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", name):
        return None
    for path in directory().glob(f"{name}.*"):
        if path.suffix != ".gone" and _NAME.fullmatch(path.name):
            return path
    return None


def served_as(path: Path) -> tuple[str, bool]:
    """(type, shown inline) for a kept file: only what a browser cannot run is shown."""
    kind = TYPES.get(path.suffix.lstrip("."))
    return (kind, True) if kind else ("application/octet-stream", False)
