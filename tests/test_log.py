"""`log.py`: the runner's own journal."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from support import case

from ponos import log


@case
def the_journal_is_kept_for_this_account_only(state_home: Path) -> None:
    """ponos.log came out with the umask, 0644 on most machines.

    A trace carries paths, ticket titles and the arguments of the call that
    failed, and the first `ponos doctor` after an install flagged it. The file
    the handler opens is private from its creation, and so is the next one a
    rotation opens.
    """
    previous = os.umask(0o022)
    try:
        target = log.setup(state_home / "logs" / "ponos.log")
        assert target is not None
        logging.getLogger("ponos.test").warning("written", extra=log.FILE_ONLY)
        assert target.stat().st_mode & 0o777 == 0o600, oct(target.stat().st_mode)
        for handler in logging.getLogger(log.NAME).handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                handler.doRollover()
        logging.getLogger("ponos.test").warning("after", extra=log.FILE_ONLY)
    finally:
        os.umask(previous)
    assert target.stat().st_mode & 0o777 == 0o600, oct(target.stat().st_mode)
    assert (target.parent / "ponos.log.1").stat().st_mode & 0o777 == 0o600
