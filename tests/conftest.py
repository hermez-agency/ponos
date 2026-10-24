"""The two suites, as pytest collects them.

`tests/run.py` and `tests/functional.py` stay scripts that run with `python3`
alone, so their cases are plain functions registered with `@case` rather than
`test_` ones, and their fixtures plain generators registered with `@fixture`
(see `support.py`). This file hands both to pytest as they are: every `@case`
of a `test_*.py` file or of `functional.py` is a test, under its own name, and
every fixture is a pytest fixture of the same name — for what pytest adds on
top: `-k` to run one case, `-x`, `--durations`, coverage, and `-n auto`.

    uv run pytest                      # both suites
    uv run pytest -m "not functional"  # the pure part only
    uv run pytest tests/test_update.py # one module
"""

from __future__ import annotations

import inspect

import functional  # noqa: F401 — for its fixture
import pytest
import support

# What `run.main()` sets before its first case — set once here, at collection,
# since a few cases read it before any fixture would run. Each xdist worker
# imports this file, and so gets directories of its own.
support.isolate()


def pytest_pycollect_makeitem(collector, name, obj):
    if (
        inspect.isfunction(obj)
        and obj.__module__ == collector.obj.__name__
        and obj in support.CASES
    ):
        item = pytest.Function.from_parent(collector, name=name)
        if obj.__module__ == "functional":
            item.add_marker(pytest.mark.functional)
        return item
    return None


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """A case's `support.Skip` is a pytest skip, with its reason."""
    try:
        return (yield)
    except support.Skip as skipped:
        pytest.skip(str(skipped))


def _pytest_fixture(name: str, function):
    def fixture(request):
        yield from function(request.function)

    return pytest.fixture(name=name)(fixture)


for _name, _function in support.FIXTURES.items():
    globals()[_name] = _pytest_fixture(_name, _function)
