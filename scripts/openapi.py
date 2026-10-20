#!/usr/bin/env python3
"""Print the console's OpenAPI schema, without starting a console.

What `npm run types` reads to write `frontend/src/lib/api-types.d.ts`: the
schema FastAPI would serve at `/openapi.json`, built from the routes alone —
no configuration, no board, no port. Run with a Python that has FastAPI;
the machine's `python3` usually does not, so this starts again in the
checkout's `.venv` when it can, as `tests/run.py` does.

The titles are left out: Pydantic writes one for every field, from its name
("Project Id" over `project_id`), and the generator would turn each into a
comment that says nothing the name does not.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_VENV = ROOT / ".venv" / "bin" / "python"
if (
    importlib.util.find_spec("fastapi") is None
    and _VENV.is_file()
    and Path(sys.prefix).resolve() != _VENV.parents[1].resolve()
):
    os.execv(_VENV, [str(_VENV), *sys.argv])

sys.path.insert(0, str(ROOT / "src"))

from ponos.web import app  # noqa: E402


def untitled(node: Any, properties: bool = False) -> Any:
    """The schema without its titles — but with a property called `title`."""
    if isinstance(node, dict):
        return {
            key: untitled(value, key == "properties")
            for key, value in node.items()
            if properties or not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [untitled(value) for value in node]
    return node


def main() -> int:
    json.dump(untitled(app.schema()), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
