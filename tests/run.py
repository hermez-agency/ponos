#!/usr/bin/env python3
"""The pure part of ponos, under assertions.

    uv run python tests/run.py   # or python3, with requirements.txt installed

No framework, and no dependency beyond the runner's own (`requirements.txt`, in
the `.venv` `uv sync` makes): a test suite that needs more of an install than
the runner does is a test suite that stops being run. Everything
here is pure — nothing touches Notion, git, the network or the disk beyond a
temporary file.

The console's cases start the real FastAPI application. A `python3` without
FastAPI runs the suite again under the checkout's `.venv` — what `uv sync`
makes — so that the command stays the same; without either, those cases fail
and say why.

What is covered is what has already gone wrong once, or would go wrong silently:
identifiers that collide, a status name that does not exist, markdown that
reaches Notion as a wall of text, a summary that keeps its verdict.

The cases themselves live one file per module, in `tests/test_<module>.py`, and
register with `@case`; this script imports every one of those files and runs
what they registered, in the order of their names. `uv run pytest` collects the
very same cases — see `conftest.py`.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

# See the docstring: the console's cases need what the checkout's environment holds.
_VENV = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"
if (
    __name__ == "__main__"
    and importlib.util.find_spec("fastapi") is None
    and _VENV.is_file()
    and Path(sys.prefix).resolve() != _VENV.parents[1].resolve()
):
    os.execv(_VENV, [str(_VENV), *sys.argv])

import support  # noqa: E402


def main() -> int:
    for path in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        importlib.import_module(path.stem)
    return support.run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
