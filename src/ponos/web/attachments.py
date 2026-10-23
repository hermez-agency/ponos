"""What a message to the workspace carries besides its words.

The session on the other side is Claude Code, and Claude Code does not take a
file in a request: it reads one from the disk, with the same tool it reads
source with. So an attachment is never *sent* anywhere. It is written to a
folder of the conversation, under the runner's state — not in a repository,
where it would end up in somebody's commit — and the message names its absolute
path, with a word on how to look at it.

That word is not the same for every kind of file, and it is the whole of the
difference:

- an **image** or a **PDF** is read as it is: the Read tool shows the first and
  pages through the second;
- a **video** is not something the session can watch. When `ffmpeg` is here, a
  handful of frames are drawn from it and those are what it looks at; when it
  is not, the message says so, so that the answer does too instead of guessing
  what was in the clip;
- **anything else** — a spreadsheet, a Word file, a CSV — is a file on a
  machine where the session has a shell, which is enough.

What is accepted is a list, and a short one, rather than "whatever was dropped":
this folder is served back to the page for its thumbnails, and a file the
console never meant to hold — an HTML page, an SVG — would be served from the
console's own origin.

The files belong to one conversation and leave with it: a new conversation
empties the folder, and whatever a conversation nobody closed left behind goes
after `web.attachment_days`. Meanwhile they are nobody else's to read — a
screenshot pasted in the chat shows whatever was on the screen: the folders are
`0700` and the files `0600` from their first byte (see `disk.py`).
"""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .. import disk

# Extension → (kind, the type it is served back as). The type is ours, never
# the browser's: what the page announced is not what decides how it is served.
ACCEPTED: dict[str, tuple[str, str]] = {
    "png": ("image", "image/png"),
    "jpg": ("image", "image/jpeg"),
    "jpeg": ("image", "image/jpeg"),
    "webp": ("image", "image/webp"),
    "gif": ("image", "image/gif"),
    "mp4": ("video", "video/mp4"),
    "webm": ("video", "video/webm"),
    "mov": ("video", "video/quicktime"),
    "pdf": ("document", "application/pdf"),
    "txt": ("document", "text/plain; charset=utf-8"),
    "md": ("document", "text/plain; charset=utf-8"),
    "csv": ("document", "text/plain; charset=utf-8"),
    "json": ("document", "text/plain; charset=utf-8"),
    "docx": (
        "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "xlsx": ("document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}

# How many frames a video is looked at through. Enough to tell a screen
# recording's steps apart, few enough to read in one breath.
FRAMES = 8
FFMPEG_TIMEOUT = 120

# The pasted screenshot has no name of its own worth keeping; this is the one
# it gets, and the one a name made only of forbidden characters falls back on.
UNNAMED = "file"

_ID = re.compile(r"[0-9a-f]{12}")


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def accepted(name: str) -> bool:
    return extension(name) in ACCEPTED


def safe_name(name: str) -> str:
    """A file name that stays in its folder and reads like the one dropped.

    Only the last component, and none of the characters a shell or a path would
    read as something else: the name ends up in a prompt as well as on disk.
    """
    base = Path(name.replace("\\", "/")).name
    cleaned = re.sub(r"[^\w.\- ]+", "-", base, flags=re.UNICODE).strip(" .-")
    return cleaned[:120] or UNNAMED


class Source(Protocol):
    """What a file is copied from: an open file, or a request's body read as it comes."""

    def read(self, size: int, /) -> bytes: ...


@dataclass
class Attachment:
    id: str
    name: str
    path: Path

    @property
    def kind(self) -> str:
        return ACCEPTED.get(extension(self.name), ("document", ""))[0]

    @property
    def type(self) -> str:
        return ACCEPTED.get(extension(self.name), ("", "application/octet-stream"))[1]

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "type": self.type.split(";", 1)[0],
            "size": self.size,
        }


class TooLarge(ValueError):
    """Past `web.attachment_max_mb`: refused before a byte of it is kept."""


class Folder:
    """One conversation's files: `<root>/<conversation>/<id>-<name>`."""

    def __init__(self, root: Path, conversation: str) -> None:
        self.root = root
        self.conversation = conversation
        self.path = root / conversation

    def save(self, name: str, source: Source, length: int, limit: int) -> Attachment:
        """Copy `length` bytes from `source` into the folder, or refuse them.

        The limit is checked against what the request announces *and* against
        what actually arrives: a length that lied is caught at the first byte
        past it, and what was written is removed.
        """
        if not accepted(name):
            offered = ", ".join(sorted(ACCEPTED))
            raise ValueError(f"“{name}” is not a kind of file the console takes — only {offered}")
        if length > limit:
            raise TooLarge(
                f"“{name}” is {_megabytes(length)}, past the {_megabytes(limit)} a file may be "
                "(web.attachment_max_mb)"
            )
        if length <= 0:
            raise ValueError(f"“{name}” is empty")
        disk.private_dir(self.root)
        disk.private_dir(self.path)
        identifier = secrets.token_hex(6)
        kept = safe_name(name)
        if not accepted(kept):
            kept = f"{UNNAMED}.{extension(name)}"
        target = self.path / f"{identifier}-{kept}"
        written = 0
        try:
            with open(target, "wb", opener=disk.opener()) as out:
                while written < length:
                    chunk = source.read(min(1 << 16, length - written))
                    if not chunk:
                        break
                    written += len(chunk)
                    out.write(chunk)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        if written < length:
            target.unlink(missing_ok=True)
            raise ValueError(f"“{name}” arrived cut short ({written} of {length} bytes)")
        return Attachment(identifier, kept, target)

    def find(self, identifier: str) -> Attachment:
        if not _ID.fullmatch(identifier or ""):
            raise LookupError(f"no such attachment: {identifier}")
        for path in self.path.glob(f"{identifier}-*"):
            if path.is_file():
                return Attachment(identifier, path.name[len(identifier) + 1 :], path)
        raise LookupError(
            f"no such attachment: {identifier} — it was removed, or the conversation is over"
        )

    def remove(self, identifier: str) -> None:
        attachment = self.find(identifier)
        attachment.path.unlink(missing_ok=True)
        shutil.rmtree(_frames_dir(attachment.path), ignore_errors=True)

    def clear(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def prune(root: Path, days: int, now: float | None = None) -> int:
    """Remove what has sat in `root` longer than `days`; say how many files went.

    By age of the file rather than of the conversation: a conversation that goes
    on for a month keeps what was dropped in it this week.
    """
    if not root.is_dir():
        return 0
    horizon = (now if now is not None else time.time()) - days * 86400
    removed = 0
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            try:
                old = path.stat().st_mtime < horizon
            except OSError:
                continue
            if not old:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
                removed += 1
        try:
            folder.rmdir()  # only if nothing is left in it
        except OSError:
            pass
    return removed


def ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


def _frames_dir(path: Path) -> Path:
    return path.with_name(f"{path.name}.frames")


def frames(path: Path, count: int = FRAMES) -> list[Path]:
    """A few stills spread along a video, drawn once and kept beside it.

    Spread by duration when `ffprobe` can say it, one every five seconds when it
    cannot. Nothing when `ffmpeg` is missing or fails: the caller says so.
    """
    binary = ffmpeg()
    if not binary:
        return []
    out = _frames_dir(path)
    kept = sorted(out.glob("frame-*.jpg"))
    if kept:
        return kept
    every = 5.0
    probe = shutil.which("ffprobe")
    if probe:
        try:
            said = subprocess.run(
                [
                    probe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
            every = max(0.5, float(said) / count)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    disk.private_dir(out)
    try:
        subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-y",
                "-i",
                str(path),
                "-vf",
                f"fps=1/{every:.3f},scale='min(1280,iw)':-2",
                "-frames:v",
                str(count),
                str(out / "frame-%02d.jpg"),
            ],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(out.glob("frame-*.jpg"))


def brief(attachments: list[Attachment]) -> str:
    """The part of the message that says what came with it, and how to read it."""
    if not attachments:
        return ""
    lines = [
        "Attached to this message — files on this machine. Read them from their paths "
        "before answering; the message is about them.",
    ]
    for attachment in attachments:
        head = f"- {attachment.name} ({attachment.kind}, {_megabytes(attachment.size)}): {attachment.path}"
        suffix = extension(attachment.name)
        if attachment.kind == "image":
            lines.append(f"{head}\n  An image: look at it with the Read tool.")
        elif suffix == "pdf":
            lines.append(f"{head}\n  A PDF: read it with the Read tool, which pages through it.")
        elif attachment.kind == "video":
            stills = frames(attachment.path)
            if stills:
                listed = "\n".join(f"    {still}" for still in stills)
                lines.append(
                    f"{head}\n  A video, which cannot be watched as such: {len(stills)} frames "
                    f"were taken along it, in order — look at them with the Read tool:\n{listed}"
                )
            elif not ffmpeg():
                lines.append(
                    f"{head}\n  A video, and ffmpeg is not installed on this machine, so no frame "
                    "could be taken from it. You cannot see what is in it: say so in your "
                    "answer rather than guess."
                )
            else:
                lines.append(
                    f"{head}\n  A video, and ffmpeg could not take a frame from it. You cannot "
                    "see what is in it: say so rather than guess."
                )
        elif suffix in ("txt", "md", "csv", "json"):
            lines.append(f"{head}\n  Text: read it with the Read tool.")
        else:
            lines.append(
                f"{head}\n  An Office file: open it with what this machine has — python's "
                "zipfile on its XML, or a library if one is installed."
            )
    return "\n".join(lines)


def _megabytes(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".0 MB", " MB")
