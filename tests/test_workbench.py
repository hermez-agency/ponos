"""`scripts/workbench.py`: what the e2e console and the demo stand on, and what it keeps them from reaching."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path
from types import ModuleType
from unittest import mock

from support import ROOT, case


def _workbench() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "workbench_script", ROOT / "scripts" / "workbench.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@case
def a_staged_console_never_reaches_the_desktop() -> None:
    # A console of fixtures that notified the desktop would post, on the real
    # session bus, a question about a ticket that does not exist, linked to the
    # real console's port: off in its configuration, and no bus to find anyway.
    from ponos import config

    workbench = _workbench()
    with (
        tempfile.TemporaryDirectory() as here,
        mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}),
    ):
        workbench.stage(Path(here), token=None)
        assert "DBUS_SESSION_BUS_ADDRESS" not in os.environ
        assert config.load(Path(os.environ["PONOS_CONFIG"])).notify.desktop is False
