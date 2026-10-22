"""What every other piece of a run has under its hand.

A run is deliberately *one* object: one store, one reading of the
workspace, one cache of a page's comments, one ledger of what has been said and
one lock over it. Two of them would mean two claims on the same ticket, the
same thread fetched twice, and a comment answered by whichever half read it
last — so the state below is not split, and cannot be.

What was split is the work. Each responsibility of a run — reading the board,
writing on a ticket, preparing one, executing it, delivering it, answering a
comment — is a class of its own in a module of its own, and `Runner` is those
classes put together over this one. A class that *adds methods* to the run
rather than a collaborator holding a reference back to it: the state stays in
one place, every call site stays the plain `self._fail(...)` it has always
been, and each module reads as the one chapter it is.

Which leaves this module as the bottom of that pile: the configuration, the
client, the caches, what the runner says out loud, and the three things a run
resolves once and re-reads all day.
"""

from __future__ import annotations

import logging
import socket
import threading
from datetime import datetime

from . import channels, conversation, journal, legacy, notify, provider, store
from . import voice as voice_module
from . import workspace as workspace_module
from .config import Config
from .projects import Resolver
from .ticket import Ticket

logger = logging.getLogger(__name__)


class Base:
    """The state of one run, and the little every module of it needs."""

    def __init__(
        self,
        config: Config,
        *,
        dry_run: bool = False,
        quiet: bool = False,
        announce_idle: bool = True,
    ) -> None:
        self.config = config
        self.dry_run = dry_run or config.runner.dry_run
        self.quiet = quiet
        # At a ten-second cadence, saying "nothing to do" writes six lines a
        # minute into the systemd journal forever, and buries the runs that
        # matter. A terminal wants the reassurance; a log does not.
        self.announce_idle = announce_idle
        # The board, whichever one the configuration asked for: Notion, a
        # directory of Markdown files, or the two kept in step. Nothing above
        # this line knows which — see store.py.
        self.client = store.open(config, dropped=self._dropped)
        self.resolver = Resolver(config.runner.workspace_root, config.projects, config.github)
        self.agent_label = f"ponos@{socket.gethostname()}"
        self._workspace: workspace_module.Workspace | None = None
        # The comments of a page, read once per run. Three things want them —
        # what wakes a ticket, what goes into its prompt, and what is waiting
        # for an answer — and asking Notion three times for the same thread is
        # how a board with forty tickets becomes a rate limit problem.
        self._comments: dict[str, list[store.Comment]] = {}
        self._ledger: conversation.Ledger | None = None
        self._ledger_lock = threading.Lock()
        self._spellings: tuple[str, ...] | None = None
        self._me: str | None = None
        self._identity_error = ""
        # The tickets this run is about to handle. A comment on one of them is
        # already going into its prompt: answering it as well would be the
        # runner talking over itself.
        self._claimed: set[str] = set()
        # What the last `deliver` left for later, so a pass can say so.
        self._deferred: list[tuple[Ticket, datetime]] = []
        # How many pull requests this runner has merged into each repository,
        # and how far that count had gone when a ticket was last replayed —
        # so that a replay its own queue made necessary is not held against
        # that ticket. See `Delivery._forgiven`.
        self._landed: dict[str, int] = {}
        self._replayed_after: dict[str, int] = {}
        self._landed_lock = threading.Lock()
        # One merge at a time per repository: the line a validated pull request
        # waits in for its turn. See `Delivery._queue`.
        self._queues: dict[str, threading.Lock] = {}
        # Whether this run has already said it cannot read the subscription's
        # usage. Said once — see `under_reserve`, which asks at every free place.
        self._usage_warned = False
        # Same, for the memory guard: see `Board.room_for_a_session`.
        self._memory_warned = False
        # And for the disk guard, with the time of its last emergency tidy.
        self._disk_warned = False
        self._disk_tidied = 0.0
        # The columns a write of this run left out because the board has none
        # by that name. Each is said once — see `_dropped`.
        self._unwritten: set[tuple[str, str]] = set()
        # The run each ticket in flight is writing into the local journal,
        # opened with its session and closed by `_guarded` once the ticket's
        # outcome is known — see journal.py.
        self._journals: dict[str, journal.Run] = {}
        # Why each ready ticket the last reading did not take was left there,
        # and what the journal was last told of it — see `Board.explain`. None
        # until the first look, so that a record left by a pass that died is
        # replaced even when this one holds nothing back.
        self._holding: dict[str, tuple[Ticket, str]] = {}
        self._explained: dict[str, str] | None = None

    @property
    def agent_labels(self) -> set[str]:
        """This machine's label, and the one it wrote before the rename.

        A migration filet: the tickets it took then still say the old name in
        their Runner column, and they are its own all the same.
        """
        host = self.agent_label.partition("@")[2]
        return {self.agent_label, f"{legacy.OLD}@{host}"}

    @property
    def workspace(self) -> workspace_module.Workspace:
        """The databases and the standing context, resolved once per run.

        Once, because a run can hold several tickets and they all read the same
        thing — and because the context page would otherwise be fetched again
        for every ticket, to be told the same story.
        """
        if self._workspace is None:
            self._workspace = workspace_module.resolve(self.client, self.config.notion)
        return self._workspace

    @property
    def database(self) -> str:
        """The tickets database ID, resolved once for the whole session."""
        return self.workspace.tickets

    @property
    def voice(self) -> voice_module.Voice:
        """Everything the runner says on a ticket, in the configured language.

        Read off the configuration each time rather than kept, so that a file
        edited in the console — where `runner.language` is one field of a form —
        is heard on the next run without the service being restarted.
        """
        return voice_module.Voice(self.config.runner.language)

    @property
    def environment(self) -> dict[str, str]:
        """What every session this run starts is given, beyond what it inherits.

        The OpenRouter key when there is one, the Anthropic key when that is the
        provider, and nothing at all otherwise — see provider.py. Read off the
        configuration each time, for the same reason as `voice`: a key typed
        into the console is a key the next run uses.
        """
        return provider.environment(self.config)

    def environment_for(self, model: str) -> dict[str, str]:
        """`environment`, for a session about to run on `model`.

        A model named as an OpenRouter slug (`openai/gpt-5`) is only reachable
        through OpenRouter, whichever provider answers the other sessions: the
        ticket's Model column says where it goes.
        """
        return provider.environment(self.config, model)

    def say(self, message: str) -> None:
        if not self.quiet:
            # Onto the standard output, which the systemd journal keeps, and into
            # ponos.log — masked on the way, see log.py.
            logger.info(message)

    def _dropped(self, database: str, name: str) -> None:
        """A write left `name` out: the board has no such column. Said once a run.

        Once, and not at every ticket: the column is missing for all of them,
        and the progress line alone is rewritten every few seconds. But said,
        because a column the configuration names and the board does not have
        is a feature switched off without anybody having switched it — the
        claims went unsigned for a day, and the abandoned tickets with them.
        """
        if (database, name) in self._unwritten:
            return
        self._unwritten.add((database, name))
        cost = store.lost(self.config.notion, name) if database == self.database else ""
        self.say(
            f"  ! “{name}” is not a column of the board — left unwritten"
            + (f": {cost}" if cost else "")
            + " (ponos doctor)"
        )

    def _notify(
        self,
        title: str,
        body: str,
        *,
        urgent: bool = False,
        warning: bool = False,
        link: str = "",
        pull_request: str = "",
    ) -> None:
        if self.config.notify.desktop and not self.dry_run:
            opening = self.voice.say("open-ticket")
            # A desktop draws the default action as a click on the notification,
            # not as a button: with a pull request beside it, the ticket needs
            # one of its own to still be seen as a choice.
            buttons = (
                ((self.voice.say("see-pull-request"), pull_request), (opening, link))
                if link and pull_request
                else ()
            )
            notify.send(
                title,
                body,
                urgent=urgent,
                warning=warning,
                link=link,
                action=opening,
                buttons=buttons,
            )

    def _announce(self, title: str, body: str) -> None:
        """Something about the runner itself, said everywhere you are reachable.

        Not `_tell`, which is about a ticket: this has no page to link to and no
        verdict to open with, and it is not filtered by `notify.events` either —
        those name the three moments of a *ticket*, and "the runner has stopped
        starting things" is not one of them. It is worth a phone precisely
        because nothing on the board will say it.
        """
        self._notify(title, body)
        settings = self.config.notify
        if self.dry_run or not settings.remote:
            return
        channels.announce(settings, f"{voice_module.MARKS['waiting']} {title}\n{body}")
