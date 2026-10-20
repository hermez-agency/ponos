"""The runner's own journal: what it said, and every error it caught, with its trace.

For a long time the runner had no log but its standard output: `say` printed
a line, systemd's journal kept it, and an error caught on the way was turned
into a sentence or into nothing. The blockages that cost the most — worktrees
left behind, an update that would not finish, a migration — all had a symptom
somebody could see and a cause nobody could, because the trace had been
dropped where the exception was caught. And the console did not log at all:
a route that failed answered a 500 and kept the reason to itself.

So there is one `logging` tree, under the logger called `ponos`, and every
module asks it for its own (`logging.getLogger(__name__)`). Two handlers:

- **the standard output**, as before, and unformatted: `say` writes there
  what it always printed, and journald keeps it as it always has — the line
  only, never the trace under it, which would bury what it says. It is the
  stream of the moment — `sys.stdout` when the line is written, not when the
  handler was made, so that what replaces it (a test, a redirection) hears it;
- **a file**, `ponos.log` beside the session logs, dated and levelled, which
  `ponos logs --service` and the console's settings show. It turns over at a
  megabyte and keeps five behind: a journal is read for the last days, not
  kept for the year. The runner's passes and the console are two processes
  writing it; whichever turns it over first, the other notices the file it
  holds is no longer `ponos.log` and opens the new one.

**A trace the runner already said in its own words goes to the file only.**
Most errors it catches are already told — a `say`, a line of `doctor`, a
notice on the console's page — and repeating them on the standard output, as
another sentence, would change what somebody reads there. Those are logged
with `extra=FILE_ONLY`: the file has the trace, the output keeps its line. An
error that used to be silent is written to both.

**Nothing secret reaches either.** A filter on both handlers renders each
line, trace included, and passes it through `vault.mask` (the values this
process read from a vault) then `redaction.masked` (the tokens whose shape
gives them away): a trace prints the arguments of the call that failed, and a
token is often one of them.

The standard output is set up as soon as the package is imported (see
`__init__.py`), whoever imports what. The file is only opened by `setup`,
which the CLI calls once it knows what it is running: a test that never asks
for the file never writes in the state directory.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from . import redaction, vault

NAME = "ponos"
FILE = "ponos.log"
# A megabyte a file, five kept: a few weeks of a busy runner, and nothing that
# fills a disk.
SIZE = 1_000_000
KEPT = 5
# What `tail` reads at most: the end of the file, not the whole of it.
TAIL_BYTES = 256_000
# `logger.exception(..., extra=FILE_ONLY)`: the trace of an error already said.
FILE_ONLY = {"file_only": True}


def _clean(text: str) -> str:
    return redaction.masked(vault.mask(text))


class Masked(logging.Filter):
    """Render a record once, and mask what it says — the message and its trace."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _clean(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = _clean(logging.Formatter().formatException(record.exc_info))
        if record.stack_info:
            record.stack_info = _clean(record.stack_info)
        return True


class _Stdout(logging.StreamHandler):
    """The standard output of the moment, flushed at every line as `print` was."""

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


class _Said(logging.Formatter):
    """The line as it was said, as `print` wrote it: no date, no level, no trace."""

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


class _Rotating(logging.handlers.RotatingFileHandler):
    """A rotating file two processes write: reopened when the other turned it over."""

    def emit(self, record: logging.LogRecord) -> None:
        if self.stream is not None:
            try:
                on_disk = os.stat(self.baseFilename)
                held = os.fstat(self.stream.fileno())
                moved = (on_disk.st_dev, on_disk.st_ino) != (held.st_dev, held.st_ino)
            except OSError:
                moved = True
            if moved:
                self.stream.close()
                self.stream = None  # type: ignore[assignment]
        if self.stream is None:
            self.stream = self._open()
        super().emit(record)


def _root() -> logging.Logger:
    root = logging.getLogger(NAME)
    if not any(isinstance(handler, _Stdout) for handler in root.handlers):
        handler = _Stdout()
        handler.setFormatter(_Said())
        handler.addFilter(Masked())
        handler.addFilter(lambda record: not getattr(record, "file_only", False))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        # The tree is the runner's own: nothing above it is asked to print it twice.
        root.propagate = False
    return root


_root()


def path() -> Path:
    """Where the journal is written: beside the session logs, under the state directory."""
    from . import state  # here: the configuration it reads logs through this module

    return state.logs_dir() / FILE


def setup(target: Path | None = None) -> Path | None:
    """Write the journal to `target` (`ponos.log` by default) from now on.

    Once per file: a second call with the same file changes nothing, one with
    another file — a test's — replaces the first. None when the file cannot be
    opened, a read-only state directory: the standard output is still there.
    """
    root = _root()
    try:
        target = target or path()
    except OSError:
        return None
    for handler in list(root.handlers):
        if isinstance(handler, _Rotating):
            if Path(handler.baseFilename) == target.absolute():
                return target
            root.removeHandler(handler)
            handler.close()
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handler = _Rotating(target, maxBytes=SIZE, backupCount=KEPT, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    handler.addFilter(Masked())
    root.addHandler(handler)
    return target


def close() -> None:
    """Stop writing the file — for the tests, whose state directories come and go."""
    root = _root()
    for handler in list(root.handlers):
        if isinstance(handler, _Rotating):
            root.removeHandler(handler)
            handler.close()


def tail(lines: int = 500, target: Path | None = None) -> list[str]:
    """The journal's last `lines` lines — none when it was never written."""
    target = target or path()
    try:
        with target.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    kept = text.splitlines()
    if size > TAIL_BYTES:
        kept = kept[1:]  # the first line was cut in the middle
    return kept[-lines:] if lines > 0 else kept
