"""Writing what the runner keeps, so that neither a crash nor the umask shows.

Two ways a small file goes wrong, and both had happened here.

**Half a file.** `write_text` truncates first and writes after, and a process
killed in between — the timer's own SIGTERM, a laptop lid, a full disk — leaves
a file that reads as empty. Empty is not "unknown" for the files kept under the
state directory, it is an answer: no claims means every in-flight ticket comes
back as work to redo, no reconciliation stamps means what was deleted on one
board is created again on the other, no cursor means a channel reads a day of
messages twice. So the new content is written beside the file and renamed over
it: a rename within one directory is atomic, and a reader sees either the old
file or the new one, never the moment between them.

**A secret readable for a moment.** Writing with the umask and tightening with
`chmod` afterwards leaves a window in which a token, a password in a
configuration or a session transcript is readable by whoever the umask allows.
Created with `0o600` from its first byte, it never is.

The same goes for a directory: what the console keeps — a screenshot pasted
in the chat, a transcript — was once protected by nothing but the `0700` of
`~/.local/state`, which no longer holds when `XDG_STATE_HOME` points elsewhere,
or in the image, where `/data` is `0755`. A folder that holds them is made
`0700` itself, and one made before is tightened.
"""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Callable, Collection
from pathlib import Path
from typing import IO

PRIVATE = 0o600
PRIVATE_DIR = 0o700


def opener(mode: int = PRIVATE) -> Callable[[str, int], int]:
    """An `opener` for `open()`: created with `mode`, not with the umask's.

    A file that already existed is tightened to it too, before a byte is
    written — `os.open` alone only applies a mode to a file it creates.
    """

    def _open(path: str, flags: int) -> int:
        descriptor = os.open(path, flags, mode)
        try:
            os.fchmod(descriptor, mode)
        except OSError:
            pass  # not ours to change: a file somebody else owns stays theirs
        return descriptor

    return _open


def private_dir(path: Path) -> Path:
    """`path`, made if it was not there, and only this account's to enter.

    `mkdir` gives its mode to what it creates and to nothing else: a directory
    already there, made with the umask, is tightened rather than left as it was.
    """
    path.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
    tighten(path)
    return path


def tighten(path: Path) -> bool:
    """Take from group and others whatever they may do with `path`; say if it changed.

    A link is left alone: `chmod` would follow it to whatever it points at.
    """
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not mode & 0o077:
            return False
        path.chmod(stat.S_IMODE(mode) & 0o700)
    except OSError:
        return False  # not ours to change, or gone meanwhile
    return True


def open_to_others(root: Path, skip: Collection[str] = ()) -> list[Path]:
    """What under `root` group or others may read or enter, `root` included.

    `skip` names folders at the top of `root` that are not walked.
    """
    found: list[Path] = []
    for folder, folders, files in os.walk(root):
        if folder == str(root):
            folders[:] = [name for name in folders if name not in skip]
        for name in (*folders, *files):
            path = Path(folder, name)
            try:
                mode = path.lstat().st_mode
            except OSError:
                continue
            if not stat.S_ISLNK(mode) and mode & 0o077:
                found.append(path)
    try:
        if root.stat().st_mode & 0o077:
            found.insert(0, root)
    except OSError:
        pass
    return found


def open_private(path: Path, mode: str = "w") -> IO[str]:
    """A text file opened for writing or appending, private from its creation."""
    return open(path, mode, encoding="utf-8", opener=opener())  # noqa: SIM115


def write_private(path: Path, text: str, mode: int = PRIVATE) -> None:
    """Write `text` in place, into a file nobody else could read at any point."""
    with open(path, "w", encoding="utf-8", opener=opener(mode)) as handle:
        handle.write(text)


def write_atomic(path: Path, text: str, mode: int = PRIVATE) -> None:
    """Replace `path` with `text` in one step: the old file, or the new one.

    The copy is named per process and per thread, so two writers never share
    one — the last rename wins, whole, which is what the in-memory locks around
    these files already assume. Raises OSError like `write_text` would, and
    leaves no copy behind when it does.
    """
    scratch = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        descriptor = os.open(scratch, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(scratch, path)
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass
