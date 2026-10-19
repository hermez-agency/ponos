"""The two suites, as pytest collects them.

`tests/run.py` and `tests/functional.py` stay what they were — scripts that run
with `python3` alone and register their cases with `@case` — so that the suite
never needs an install to run. This file only hands those same cases to
pytest, one test each and in the same order, for what it adds on top: `-k` to
run one case, `-x` to stop at the first failure, `--durations`, coverage
(`pytest --cov`), and a report a CI can read.

    uv run pytest                    # both suites
    uv run pytest -m "not functional"  # the pure part only, under a minute
"""

from __future__ import annotations

import pytest

import functional
import run

# What `run.main()` sets before its first case — set once here, at collection,
# since a few cases read it before any fixture would run.
run.isolate()


@pytest.mark.parametrize("case", run.CASES, ids=[case.__name__ for case in run.CASES])
def test_pure(case) -> None:
    case()


@pytest.mark.functional
@pytest.mark.parametrize(
    "case", functional.CASES, ids=[case.__name__ for case in functional.CASES]
)
def test_functional(case) -> None:
    case()
