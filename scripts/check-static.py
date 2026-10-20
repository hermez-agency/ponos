#!/usr/bin/env python3
"""Refuse a commit that changes the console's build without changing its source.

`src/ponos/web/static/` is what `npm run build` writes from `frontend/`, and the
runner serves it as it is committed: an edit made there by hand is an edit the
next build silently undoes. So a commit that stages a change under `static/`
must stage one under `frontend/` too — the source it was built from.

The question is asked of the index, not of the files pre-commit hands over:
`pre-commit run --all-files` passes every file of `static/` on a clean tree,
and a clean tree has nothing to refuse. The CI's frontend job stays the judge
of whether the build is the right one; this only catches the hand-edit before
the push. A rebuild with no source change (a new Node, say) goes through with
`SKIP=static-built-from-frontend git commit`.
"""

from __future__ import annotations

import subprocess
import sys

STATIC = "src/ponos/web/static/"
SOURCE = "frontend/"


def staged() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.splitlines()


def main() -> int:
    paths = staged()
    built = [path for path in paths if path.startswith(STATIC)]
    if not built or any(path.startswith(SOURCE) for path in paths):
        return 0
    print(f"{STATIC} changes without any change in {SOURCE}:")
    for path in built:
        print(f"  {path}")
    print("It is generated: change frontend/, then run `npm run build` there and commit both.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
