"""What every chapter of the console has under its hand.

The state of the one `Api` — `api.py` says why there is one, and why it is put
together out of chapters rather than written as a single class: the
configuration and the runner built on it, the three reads the console caches,
the tickets held between two readings of the board, the moves on their way to
Notion, the stream every open page listens to, and what the ideas keep while a
batch is being written. Nothing else holds any of it, so a saved file that
makes it a different board is told once: `config` drops what was read of the
old one, and `forget` what a failed call earned.

Some pieces are made the first time they are asked for rather than in
`__init__`: a test builds an `Api` without calling it, and has them all the
same.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .. import config as config_module
from .. import images, notifications
from ..config import Config
from ..runner import Runner
from . import board as board_module
from . import console, live
from . import planned as planned_module
from . import upgrade as upgrade_module

if TYPE_CHECKING:
    from .. import store


if TYPE_CHECKING:

    class Chapters(Protocol):
        """What one chapter of the console calls on another, as the type checker sees it.

        The same device as the runner's `base.Chapters`, for the same reason:
        each chapter is written against `Base` alone, and only `Api` puts them
        together, so read on its own `Projects` has no `board` — `Tickets`
        brings it. This lists what crosses from one chapter to another, with
        the signature of the chapter it comes from, which mypy holds that
        chapter to. At run time `Base` stands on `object`, and nothing here
        exists.

        A method a second chapter starts calling joins this list; one called
        only inside its own chapter stays out of it.
        """

        # tickets.py
        def board(self) -> dict[str, Any]: ...
        def create_ticket(
            self,
            title: str,
            body: str = "",
            project: str = "",
            ready: bool = True,
            priority: int | str = "",
            kind: str = "",
            model: str = "",
            subtype: str = "",
            on: str = "",
            goal: str = "",
        ) -> dict[str, Any]: ...
        def set_status(self, page_id: str, key: str, seen: str | None = None) -> dict[str, Any]: ...
        def _send(self, write: board_module.Write) -> store.Page: ...
        def _scored(self) -> bool: ...
        def _cancels(self) -> bool: ...
        def _validates(self) -> bool: ...
        def _has(self, key: str) -> bool: ...

        # projects.py
        def projects(self) -> dict[str, dict[str, Any]]: ...
        def all_projects(self) -> dict[str, Any]: ...
        def project(self, page_id: str) -> dict[str, Any]: ...
        def _shown(self, page_id: str) -> dict[str, dict[str, Any]]: ...

        # goals.py
        def _goal_index(self) -> dict[str, dict[str, Any]]: ...

        # discussion.py
        def brief(self) -> str: ...

        # upkeep.py
        def health(self) -> dict[str, Any]: ...
        def disk(self, *, fresh: bool = False) -> dict[str, Any]: ...

else:
    Chapters = object


class Base(Chapters):
    """The state of the console, and the little every chapter of it needs."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._stamp = _stamp(config.path)
        self._runner: Runner | None = None
        self._projects: dict[str, dict[str, Any]] = {}
        self._projects_at = 0.0
        self._goals: dict[str, dict[str, Any]] = {}
        self._goals_at = 0.0
        self._schema_at = 0.0
        self._images: images.Cache | None = None
        self.hub = live.Hub()
        self.commands = console.Commands(self.hub.publish, _subcommands())
        self.chat = console.Chat(config, self.hub.publish, self.brief)
        # What the ideas keep while they are found and scored: the scopes a
        # batch is being written for, under the lock that keeps a second click
        # from paying for the same batch, and who signs one written by hand.
        # See `ideas.py`.
        self._ideas_lock = threading.Lock()
        self._ideas_busy: set[str] = set()
        self._ideas_person: tuple[str, str] | None = None
        self._planned: planned_module.Planned | None = None
        self.watch = live.Watch(
            self.hub, self.board, interval=config.web.poll_seconds, status=self.synchronised
        )
        self._reader = board_module.Reader()
        self._synced: dict[str, Any] = {}
        self._briefs: dict[str, tuple[str, str]] = {}
        self._disk: tuple[float, dict[str, int], list[tuple[str, int]]] | None = None
        # The schedules being launched now: see `launch_schedule`.
        self._launching: set[str] = set()
        self._launch_guard = threading.Lock()
        # Started here and nowhere else: a move made from the console is sent
        # whether or not a browser is still open to watch it go.
        self._outbox = board_module.Outbox(outbox_path())
        self._outbox.start(self._send, self.watch.nudge)
        self._upgrade = upgrade_module.Upgrade(
            self.hub.publish, lambda: self.config.runner, self._restarting_would_cut
        )

    # -- the pieces underneath ------------------------------------------------

    @property
    def config(self) -> Config:
        """The configuration, reread when the file on disk has changed.

        `ponos config` edits the same file the console is running on,
        and a console that had to be restarted to notice would be a console
        people restart all day.
        """
        stamp = _stamp(self._config.path)
        if stamp != self._stamp:
            try:
                fresh = config_module.load(self._config.path)
            except config_module.ConfigError:
                return self._config  # a half-saved file: keep what works
            self._stamp = stamp
            self._config = fresh
            self._runner = None
            self._projects = {}
            # Another file may be another board: what was held was held of
            # the old one.
            self._reader = board_module.Reader()
            self.chat.config = fresh
        return self._config

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.config, quiet=True)
        return self._runner

    @property
    def images(self) -> images.Cache:
        """The projects' pictures, as this machine keeps them. See `images.py`."""
        if self._images is None:
            self._images = images.Cache(images.root())
        return self._images

    @property
    def planned(self) -> planned_module.Planned:
        """The scheduled search for ideas. Made when first asked for: an `Api` a test built without `__init__` has one too."""
        if getattr(self, "_planned", None) is None:
            # `self` is an `Api`, the one class built over `Base`, and
            # `Planned` is handed the whole of it.
            self._planned = planned_module.Planned(self)  # type: ignore[arg-type]
        return self._planned  # type: ignore[return-value]

    @property
    def reader(self) -> board_module.Reader:
        if getattr(self, "_reader", None) is None:
            self._reader = board_module.Reader()
        return self._reader

    @property
    def outbox(self) -> board_module.Outbox:
        """The writes waiting for Notion. In memory, and idle, for an `Api` a
        test built without `__init__`: only the console's own sends anything."""
        if getattr(self, "_outbox", None) is None:
            self._outbox = board_module.Outbox()
        return self._outbox

    @property
    def upgrade(self) -> upgrade_module.Upgrade:
        """The update a click starts. See `upgrade.py` for why it waits for the lock."""
        if getattr(self, "_upgrade", None) is None:
            self._upgrade = upgrade_module.Upgrade(
                self.hub.publish, lambda: self.config.runner, self._restarting_would_cut
            )
        return self._upgrade

    def _restarting_would_cut(self) -> str:
        """What of the console's own a restart would interrupt, or ""."""
        if self.chat.busy:
            return "a conversation turn is being answered"
        if self.commands.busy:
            return "a command is running"
        return ""

    def forget(self) -> None:
        """Drop the caches. What a failed Notion call earns, so the next retries."""
        self._runner = None
        self._projects = {}
        self._projects_at = 0.0
        self._schema_at = 0.0

    def forget_projects(self) -> None:
        """Read the projects again next time: one was created or renamed meanwhile."""
        self._projects = {}
        self._projects_at = 0.0

    def resynchronise(self) -> None:
        """ "Resynchronise now": the whole board read again, the failed writes
        tried again, and the conflicts let go of — see `Outbox.retry`."""
        self.forget()
        self.reader.reconcile_next()
        self.outbox.retry()
        self.watch.nudge()

    def read_notifications(self, identifier: int | None) -> dict[str, Any]:
        """One notification read, or all of them — and the bell published at once."""
        notifications.read(identifier)
        self.watch.ring()
        return notifications.recent()

    def synchronised(self) -> dict[str, Any]:
        """When the board last agreed with Notion, and what does not. See `board.describe`."""
        return dict(getattr(self, "_synced", {}) or {})


def outbox_path() -> Path:
    return config_module.state_dir() / "web" / "outbox.json"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _stamp(path: Path) -> tuple[float, float]:
    """When the configuration last changed — the file, or the secrets beside it.

    A token is written to `secrets.env` alone: watching `config.toml` only, the
    console kept the token it had before the first connection pasted one, and
    went on saying there was none until it was restarted.
    """
    return _mtime(path), _mtime(config_module.secrets_path(path))


def _subcommands() -> tuple[str, ...]:
    from ..__main__ import subcommands

    return subcommands()
