"""What holds a Claude session once the runner that started it has gone.

A session used to be a child of the runner, its stream read from a pipe: kill
the runner — a restart, an update, a crash — and the CLI went with it, an
hour of work thrown away and the ticket started again from nothing. So the
session is no longer the runner's child. It is this process's, started in a
session of its own (`setsid`), which does the three things the runner used to
do on its behalf and which must not stop when the runner does:

- feed the prompt on the CLI's standard input;
- write the stream into the session's log line by line, the vault's secrets
  masked on the way, as `session._read` used to;
- write how the CLI ended into `<log>.code` once it has.

The runner reads the log and the code file instead of a pipe (`session.follow`),
and a runner started afterwards — the same daemon after an `exec`, or a new
one after a crash — reads the very same files: that is what adopting a
session is (see `adoption.py`).

**The standard library only, and nothing of Ponos.** The specification comes
on standard input, as one JSON object, and is read before anything else: the
prompt and the secrets to mask never touch the disk, and the version of Ponos
that started the session can be pruned by an update without the session
noticing. Run as `python -m ponos.tether <session id>` — the identifier in the
command line is what tells this process apart from another one that would
reuse its pid.

SIGTERM is caught rather than obeyed: the group is signalled as a whole when a
session is stopped or timed out (`session.halt`), and this process has to
outlive the CLI by the moment it takes to write its code. A handler, not
`SIG_IGN`: an ignored signal stays ignored across `exec`, and the CLI must
still die of it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any


def _mask(text: str, forms: list[str]) -> str:
    for form in forms:
        if form in text:
            text = text.replace(form, "***")
    return text


def _feed(process: subprocess.Popen[str], prompt: str) -> None:
    try:
        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.close()
    except (BrokenPipeError, OSError):
        pass


def _write_code(path: Path, code: int) -> None:
    """Atomically: a reader that sees the file sees the whole number."""
    partial = path.with_name(path.name + ".part")
    partial.write_text(str(code), encoding="utf-8")
    os.replace(partial, path)


def main(spec: dict[str, Any]) -> int:
    signal.signal(signal.SIGTERM, lambda *_: None)
    signal.signal(signal.SIGHUP, lambda *_: None)
    log = Path(spec["log"])
    code_path = Path(spec["code"])
    forms = [str(form) for form in spec.get("forms") or []]
    opener = lambda path, flags: os.open(path, flags, 0o600)  # noqa: E731
    with (
        open(log, "w", encoding="utf-8", opener=opener) as journal,
        open(spec["stderr"], "w", encoding="utf-8", opener=opener) as errors,
    ):
        try:
            process = subprocess.Popen(
                spec["command"],
                cwd=spec["cwd"],
                stdout=subprocess.PIPE,
                stderr=errors,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=spec["environment"],
            )
        except OSError as error:
            errors.write(f"{error}\n")
            _write_code(code_path, 127)
            return 127
        threading.Thread(
            target=_feed, args=(process, str(spec.get("prompt", ""))), daemon=True
        ).start()
        assert process.stdout is not None
        for line in process.stdout:
            journal.write(_mask(line, forms))
            journal.flush()
        code = process.wait()
    _write_code(code_path, code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(json.loads(sys.stdin.read())))
