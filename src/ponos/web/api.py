"""What the console can ask for, and what it is allowed to change.

The board stays Notion's. Nothing here is a second database: a ticket read is a
ticket read from Notion, a ticket moved is a `PATCH` on the same page you would
have dragged with your thumb. The console adds what Notion cannot do — the live
steps of a running session, the CLI, and a conversation about the whole
workspace — and duplicates nothing it already does well.

Three reads are cached, because a page left open in a tab must not turn into a
full-time reader of your workspace: the configuration (reloaded when its file
changes), the project index, and the tickets database ID. The tickets
themselves are held too, and brought up to date by what changed — how, and why
a move from the console waits in a queue rather than in the browser, is
`board.py`'s to say. So is a ticket's page, while Notion says it has not been
edited — see `Api._brief`.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import (
    blocks,
    channels,
    ci,
    cleanup,
    conversation,
    credits,
    decisions,
    git,
    health,
    images,
    journal,
    log,
    models,
    notifications,
    project_settings,
    provision,
    question,
    redaction,
    resources,
    session,
    state,
    store,
    subtypes,
    sync,
    systemd,
    voice,
    worktime,
)
from .. import config as config_module
from .. import kinds as kinds_module
from .. import priority as priority_module
from .. import schedules as schedules_module
from .. import transitions as transitions_module
from .. import update as update_module
from ..config import Config
from ..runner import Runner
from ..schedules import scheduled_for
from ..ticket import short_id
from . import board as board_module
from . import console, creation, live, removal, statistics
from . import ideas as ideas_module
from . import settings as settings_module
from . import upgrade as upgrade_module

# The project index is read from one database query, not one page fetch per
# project — and kept, because projects are renamed about as often as they are
# created. Ten minutes is short enough that a new project appears on its own.
PROJECT_TTL = 600

# And the board's own shape on the same cadence, for the same reason: the Notion
# client caches a database for its lifetime, which for the console is days. A
# column added in Notion — the validated one, most of all — has to appear
# without anyone restarting anything.
SCHEMA_TTL = 600

# How many ticket pages are kept, read, while their `last_edited_time` holds.
# A ticket's page is a dozen block requests away — one to three seconds — and
# opening a ticket read it again every time. Enough for every ticket somebody
# opens in a day; the oldest goes first.
BRIEFS = 200

# Measuring the state directory walks every file of every worktree — 25 GB of
# them on the day the console started showing it. Once in a while is plenty: it
# grows by the ticket, not by the second.
DISK_TTL = 600

# The columns, in the order they are meant to be read. Anything the board
# carries that is none of them is a draft, so it is never hidden. The drafts
# come before them, whether or not the board names its own — see `_keys`.
# Blocked follows running: a ticket waiting on an answer is a ticket in
# progress that stopped, so it is read next to it. Cancelled closes the row,
# beside done: the two ends a ticket can come to. This is the one order — the
# console, the filters and the MCP tools all take it from here.
COLUMNS = ("ready", "running", "blocked", "review", "validated", "failed", "done", "cancelled")


class Api:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._stamp = _stamp(config.path)
        self._runner: Runner | None = None
        self._projects: dict[str, dict] = {}
        self._projects_at = 0.0
        self._schema_at = 0.0
        self._images: images.Cache | None = None
        self.hub = live.Hub()
        self.commands = console.Commands(self.hub.publish, _subcommands())
        self.chat = console.Chat(config, self.hub.publish, self.brief)
        self.ideas = ideas_module.Ideas(self)
        self.removal = removal.Removal(self)
        self.creation = creation.Creation(self)
        self.watch = live.Watch(
            self.hub, self.board, interval=config.web.poll_seconds, status=self.synchronised
        )
        self._reader = board_module.Reader()
        self._synced: dict = {}
        self._briefs: dict[str, tuple[str, str]] = {}
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

    def resynchronise(self) -> None:
        """ "Resynchronise now": the whole board read again, the failed writes
        tried again, and the conflicts let go of — see `Outbox.retry`."""
        self.forget()
        self.reader.reconcile_next()
        self.outbox.retry()
        self.watch.nudge()

    def read_notifications(self, identifier: int | None) -> dict:
        """One notification read, or all of them — and the bell published at once."""
        notifications.read(identifier)
        self.watch.ring()
        return notifications.recent()

    def synchronised(self) -> dict:
        """When the board last agreed with Notion, and what does not. See `board.describe`."""
        return dict(getattr(self, "_synced", {}) or {})

    # -- reading --------------------------------------------------------------

    def board(self) -> dict:
        """Every ticket, grouped the way the board groups them."""
        settings = self.config.notion
        try:
            if time.time() - self._schema_at > SCHEMA_TTL:
                self.runner.client.forget_database(self.runner.database)
                self._schema_at = time.time()
            pages = self.reader.read(
                self.runner.client, self.runner.database, settings.prop("status")
            )
        except store.StoreError:
            self.forget()
            raise
        keys = _keys(settings)
        names = _columns(settings)
        projects = self.projects()
        host = self.config.runner.session_host

        writes = self.outbox.marks()
        refused = board_module.conflicts(sync.journal(200))
        tickets = [
            board_module.settled(
                board_module.overlay(
                    self._ticket(page, names, projects, host),
                    writes.get(page.id.replace("-", "")),
                    lambda status: names.get(status, "draft"),
                ),
                refused.get(page.id.replace("-", "")),
            )
            for page in pages
        ]
        _causes(tickets)
        _checks(tickets)
        _times(tickets)
        self._synced = board_module.describe(self.reader, tickets)
        self._hold(tickets)

        # Whether this board has a validated column at all. The console offers
        # the gesture only where the runner would honour it: a button that
        # writes a status Notion does not know is a button that fails.
        validated = settings.state("validated")
        try:
            offers = validated not in (
                settings.state("review"),
                settings.state("done"),
            ) and validated in self.runner.client.options(
                self.runner.database, settings.prop("status")
            )
        except store.StoreError:
            offers = False

        # Within a column, in the order the queue takes them: the highest
        # score first, the oldest on a tie. A board with no priority column
        # keeps its alphabetical order.
        order = {key: index for index, key in enumerate(keys)}
        tickets.sort(
            key=lambda item: (
                order.get(item["column"], len(keys)),
                -(item["priority"] if item["priority"] is not None else priority_module.DEFAULT),
                item["created"] if item["priority"] is not None else "",
                item["title"].lower(),
            )
        )
        columns = [
            {"key": key, "name": _status(settings, key)}
            for key in keys
            # A board whose `blocked` and `failed` are one column must not
            # be drawn twice under two headings.
            if key == "draft"
            or _status(settings, key)
            not in [_status(settings, other) for other in keys[: keys.index(key)]]
        ]
        return {
            "tickets": tickets,
            "validate": offers,
            # And whether it has a cancelled one, for the same reason: giving a
            # ticket up is offered only where the board can say it.
            "cancel": self._cancels(),
            "columns": columns,
            "choices": self._choices(),
            # Whether a ticket can be given a score: only where the board has
            # the column, as for the choices above.
            "priority": self._scored(),
            # The sub-types, whole: the card's icon and colour, and its word —
            # one, untranslated — read off subtypes.py, never written twice.
            "subtypes": [subtype.as_dict() for subtype in subtypes.SUBTYPES],
            # What a ticket with no model of its own runs on — empty, the CLI's.
            "model": self.config.runner.model,
        }

    def _choices(self) -> dict[str, list[dict[str, str]]]:
        """What a new ticket may be given beside its title: type, sub-type, model.

        Only the columns this board has. A select offered for a column Notion
        does not carry is a value silently dropped on the way in — the form
        would be promising what the board cannot keep. The runner's own words
        come first, because they are the ones it acts on (`MODELS` is what
        `claude --model` takes); whatever else the board offers follows. A type
        is one of the four, written as the board spells it. The priority is not
        a choice but a score: see `_scored`.
        """
        settings = self.config.notion
        client, database = self.runner.client, self.runner.database
        try:
            schema = client.schema(database)
        except store.StoreError:
            return {}
        choices: dict[str, list[dict[str, str]]] = {}
        name = settings.prop("model")
        if name in schema:
            try:
                offered = client.options(database, name)
            except store.StoreError:
                offered = []
            values = list(
                dict.fromkeys([*provision.MODELS, *(value for value in offered if value)])
            )
            choices["model"] = [{"value": value, "label": value} for value in values]
        if settings.prop("type") in schema:
            choices["type"] = [
                {"value": key, "label": self.runner.kind_name(key)} for key in kinds_module.KINDS
            ]
        if settings.prop("subtype") in schema:
            # The board's option as the label: what the card is found by when
            # the filter folds it — the console says it in its own words.
            choices["subtype"] = [
                {"value": subtype.key, "label": subtype.option} for subtype in subtypes.SUBTYPES
            ]
        return choices

    def _scored(self) -> bool:
        """Whether this board has a priority column to write a score in."""
        try:
            schema = self.runner.client.schema(self.runner.database)
        except store.StoreError:
            return False
        return self.config.notion.prop("priority") in schema

    def _hold(self, tickets: list[dict]) -> None:
        """Put on every ready card why it is still there — see `board.held`.

        The timer is asked of systemd only when a card needs it: three
        `systemctl` calls at every reading of the board would be most of it.
        """
        ready = [ticket for ticket in tickets if ticket.get("column") == "ready"]
        if not ready:
            return
        configuration = self.config
        waits = {
            "credits": credits.held() if configuration.runner.wait_for_credits else 0.0,
            "reserve": credits.held(what="reserve")
            if configuration.runner.wait_for_credits
            else 0.0,
            "budget": credits.held(what="budget") if configuration.budget.daily_usd > 0 else 0.0,
        }
        clocks = {what: credits.when(until) if until else "" for what, until in waits.items()}
        passing = bool(state.running())
        timer = (
            passing
            or config_module.in_container()
            or any(clocks.values())
            or systemd.read().label == "enabled"
        )
        noted = state.held() if passing else {}
        for ticket in ready:
            ticket["held"] = board_module.held(
                ticket, noted, passing=passing, timer=timer, waits=clocks
            )

    def _ticket(self, page: store.Page, names: dict[str, str], projects: dict, host: str) -> dict:
        """One page of the tickets database, as a card reads it."""
        settings = self.config.notion
        status = str(store.read(page, settings.prop("status")) or "")
        relation = store.read(page, settings.prop("project")) or []
        project = projects.get(relation[0]) if relation else None
        session_id = _session_id(str(store.read(page, settings.prop("session")) or ""))
        moment = scheduled_for(store.read(page, settings.prop("due")))
        return {
            "id": page.id.replace("-", ""),
            "short": short_id(page.id),
            # Empty when Notion has none: "(untitled ticket)" is the console's to
            # say, in the language it is read in.
            "title": page.title,
            "url": page.url,
            "status": status,
            "column": names.get(status, "draft"),
            "project": (project or {}).get("name", ""),
            # What the card needs to draw the project's mark and link to its page
            # without asking for the project: both are already in the index.
            "project_id": (project or {}).get("id", ""),
            "project_icon": (project or {}).get("icon") or {"kind": ""},
            "kind": (project or {}).get("kind", ""),
            # The ticket's type as the board spells it — `kind` is the project's.
            "type": str(store.read(page, settings.prop("type")) or ""),
            # A code ticket's sub-type, as its key — `bug`, `docs` — or "" for
            # none, and for every ticket of another type: the column is ignored there.
            "subtype": _subtype(page, settings),
            # A score from 0 to 100, an empty cell read as 50; None where the
            # board has no such column, and the card says nothing of it.
            "priority": (
                priority_module.score(store.read(page, settings.prop("priority")))
                if settings.prop("priority") in page.properties
                else None
            ),
            "model": str(store.read(page, settings.prop("model")) or ""),
            "model_label": models.label(str(store.read(page, settings.prop("model")) or "")),
            "progress": str(store.read(page, settings.prop("progress")) or ""),
            "runner": str(store.read(page, settings.prop("agent")) or ""),
            "pull_request": str(store.read(page, settings.prop("pull_request")) or ""),
            "session": session_id,
            "session_link": session.deep_link(session_id, host=host) if session_id else "",
            "cost": store.read(page, settings.prop("cost")),
            "duration": store.read(page, settings.prop("duration")),
            "scheduled": moment.isoformat(timespec="minutes") if moment else "",
            "created": page.raw.get("created_time", ""),
            "edited": page.raw.get("last_edited_time", ""),
            # Why it stopped, from the board's « Blocage » column; `_causes`
            # falls back on the history, and keeps it on a stopped card only.
            "block": blocks.describe(blocks.known(store.read(page, settings.prop("block")))),
        }

    def ticket(self, page_id: str) -> dict:
        """One ticket, and what its page says.

        The card on the board is the row; this is the page under it — the
        brief you wrote, the report a run appended, the notes in between —
        flattened the way the runner itself reads it before it starts. It is
        the same page the ticket's discussion hangs off, so a console showing
        both is showing one thing.
        """
        settings = self.config.notion
        names = _columns(settings)
        started = time.time()
        try:
            page = self.runner.client.page(page_id)
            content = self._brief(page_id, page, started)
        except store.StoreError:
            self.forget()
            raise
        card = board_module.overlay(
            self._ticket(page, names, self.projects(), self.config.runner.session_host),
            self.outbox.marks().get(page_id.replace("-", "")),
            lambda status: names.get(status, "draft"),
        )
        _causes([card])
        _checks([card])
        _times([card])
        # A board without the duration column still ran the session: its log
        # says how long. Only here, where one ticket is read — on the board it
        # would be a log opened per card.
        if not card.get("duration"):
            card["duration"] = live.lasted(card["short"]) or card.get("duration")
        # What it runs on, said once for the page: the last session's own word,
        # then the column, then the defaults — see `models.describe`.
        last = next(iter(journal.runs(page_id, limit=1)), {})
        card["model_in_use"] = models.describe(
            card["model"],
            last.get("reported") or last.get("model") or "",
            self.config.runner.model,
        )
        # Only on the page, not on every card of the board: a prompt can be long.
        return {**card, "content": content, "on": str(store.read(page, settings.prop("on")) or "")}

    def attachment(self, block_id: str) -> str:
        """Where a picture or a file on a page is, asked when it is opened.

        A page's text names its files by block (`markdown.attached`) and the
        console draws each one from `/api/files/<block>`, which sends the
        browser on to this. Read again at every opening rather than kept like a
        project's cover: a brief's capture is looked at once, and a fresh
        address is one call — where an address kept an hour is a 403.
        """
        return self.runner.client.attachment(block_id.replace("-", ""))

    def _brief(self, page_id: str, page: store.Page, started: float) -> str:
        """What a ticket's page says, read again only once Notion says it changed.

        The row costs one request and says when the page was last touched; the
        blocks cost one per block that has children. So the row is read every
        time, and the blocks only when its `last_edited_time` moved — an edit
        anywhere in the page moves it.

        Notion gives that time to the minute. A page read during the minute it
        was edited in could be edited again in the same minute without its time
        moving, so what is read then is not kept: only a read begun after the
        edit's minute is over is. A Markdown board is not kept at all — its
        page is a file read, and a file changed by hand says nothing in its
        `edited`.
        """
        key = page_id.replace("-", "")
        edited = str(page.raw.get("last_edited_time") or "")
        held = self._briefs.get(key)
        if held and held[0] == edited:
            return held[1]
        content = self.runner.client.blocks_text(page_id, live=False)
        stamp = _instant(edited)
        if self.config.storage.mode != "markdown" and stamp is not None and started >= stamp + 60:
            self._briefs.pop(key, None)
            self._briefs[key] = (edited, content)
            while len(self._briefs) > BRIEFS:
                self._briefs.pop(next(iter(self._briefs)))
        return content

    def projects(self) -> dict[str, dict]:
        """{page id: {name, kind, …}} — one query, kept for a few minutes.

        Read from the projects database in one go rather than resolved ticket by
        ticket: resolving costs two API calls per project, and the board asks
        this question every time it refreshes.
        """
        if self._projects and time.time() - self._projects_at < PROJECT_TTL:
            return self._projects
        index: dict[str, dict] = {}
        try:
            database = self.runner.workspace.projects
            if database:
                for page in self.runner.client.query(database):
                    repository = _first(page, "Repository", "repository", "github", "repo")
                    path = _first(page, "Path", "path")
                    index[page.id] = {
                        "id": page.id.replace("-", ""),
                        "name": page.title or "(untitled project)",
                        "kind": "code" if (repository or path) else "document",
                        "url": page.url,
                        "repository": repository,
                        "path": path,
                        "description": _first(page, *creation.COLUMNS["description"]),
                        "site": _first(page, *creation.COLUMNS["site"]),
                        **self._pictures(page),
                    }
        except store.StoreError:
            # A projects database that cannot be read costs the board its
            # project names, and nothing else. The tickets still show.
            return self._projects
        self._projects = index
        self._projects_at = time.time()
        return index

    def forget_projects(self) -> None:
        """Read the projects again next time: one was created or renamed meanwhile."""
        self._projects = {}
        self._projects_at = 0.0

    def _pictures(self, page: store.Page) -> dict[str, dict]:
        """A project's cover and icon, read with the rest of the page.

        Reading the projects database is the synchronisation: what somebody
        changed in Notion is agreed on here, and a change of the console's that
        Notion refused last time is sent again. A cache that cannot be written
        costs the pictures, never the list.
        """
        client = self.runner.client
        try:
            self.images.observe(
                page, lambda slot, picture: client.set_picture(page.id, slot, picture)
            )
        except OSError:
            pass
        return self._shown(page.id)

    def _shown(self, page_id: str) -> dict[str, dict]:
        """Both pictures of a page, each at the console's own address for it."""
        bare = page_id.replace("-", "")
        shown: dict[str, dict] = {}
        for slot in store.SLOTS:
            said = self.images.shown(bare, slot)
            version = said.pop("version", "")
            if said["kind"] == "image":
                said["src"] = f"/api/projects/{bare}/image/{slot}?v={version}"
            shown[slot] = said
        return shown

    def all_projects(self) -> dict:
        """Every project this installation knows of, from wherever it knows it.

        Three sources, and the pane shows the three as one list because that is
        how somebody thinks of their projects: the board's own database; the
        `[projects]` table of the configuration, which is a path this machine
        maps a name onto; and — for either of those — where the repository
        actually turned out to be on this disk.

        A configuration entry for a project the board already has is not a
        second project: it is the same one, with its path resolved. Only a name
        the board has never heard of adds a row, and it is marked as coming from
        the file so that nobody goes looking for its page.
        """
        rows: list[dict] = []
        try:
            known = self.projects()
        except store.StoreError:
            known = {}
        overrides = dict(self.config.projects)
        for project in sorted(known.values(), key=lambda item: item["name"].lower()):
            declared = overrides.pop(project["name"], "")
            rows.append({**project, "configured": declared, "source": "board"})
        for name, path in sorted(overrides.items(), key=lambda pair: pair[0].lower()):
            rows.append(
                {
                    "id": "",
                    "name": name,
                    "kind": "code",
                    "url": "",
                    "repository": "",
                    "path": path,
                    "configured": path,
                    "source": "config",
                }
            )
        # No count of tickets per project: that was the whole tickets database
        # read again on every call, three hundred pages to write six numbers,
        # while the console already holds every ticket the stream sent it. It
        # counts them there.
        return {
            "projects": rows,
            "workspace_root": str(self.config.runner.workspace_root),
            "storage": self.config.storage.mode,
        }

    def project(self, page_id: str) -> dict:
        """One project, as the list says it, plus what is written on its page.

        The row is `all_projects`' own, so a project opened reads like the
        project listed — and what a card cannot carry is added here: the brief.
        Which is the reason a project is worth opening at all. It is not
        decoration on the page, it is standing instructions: the audience, the
        voice, the conventions, the things never to do. `projects.brief` reads
        the same text into every ticket of that project.
        """
        wanted = page_id.replace("-", "")
        row = next((item for item in self.all_projects()["projects"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no project with id {wanted}")
        # Where the clone really is, which neither declaration says when the
        # repository was found by its remote. Left out of the list: finding it
        # walks the disk, and a card has no room for it.
        located = self.runner.resolver.locate(
            row["name"], row.get("configured") or row.get("path") or "", row.get("repository") or ""
        )
        content = self.runner.client.blocks_text(page_id)
        return {
            **row,
            "located": str(located) if located else "",
            "content": content,
            "version": _digest(content),
        }

    def project_brief(self, page_id: str) -> dict:
        """The brief as the editor opens it: the text, its version, what saving it would lose.

        Read when somebody starts editing rather than with the page, because
        that is the moment the two other answers are measured from. `version`
        is what `save_project` is handed back as `base`: a brief that no longer
        says that has been written to since, and is not overwritten. `losses` is
        what the Markdown cannot hold of the page as it is now — see
        `markdown.lost` — kind by kind, for the editor to say before it saves.
        """
        client = self.runner.client
        content = client.blocks_text(page_id)
        return {
            "content": content,
            "version": _digest(content),
            "losses": client.losses(page_id),
        }

    def save_project(self, page_id: str, values: dict) -> dict:
        """Change one project page from the console.

        What a project is: its name, what it does in a sentence, its public
        address, the repository its tickets are worked in, the path this
        machine finds that repository at, and the brief. Never its tickets —
        those point at the page, and are moved on the board.

        Its type is no column: a page that names a repository or a folder is a
        code project (see `projects`). So "document" empties both, and "code"
        is refused when neither would be left — a type corrected after the
        creation is a type that holds, not one the next reading undoes.

        The columns are written under the name the page already carries:
        a project database is written by hand, so "Repository" is sometimes
        "github" and sometimes "repo", and a save that invented a second column
        beside the one somebody filled in would be a save that changes nothing
        anybody can see. `projects.py` reads them the same way.
        """
        database = self.runner.workspace.projects
        if not database:
            raise ValueError("this workspace has no projects database")
        page = self.runner.client.page(page_id)
        written: dict[str, Any] = {}
        if "repository" in values:
            column = _column(page, "Repository", "repository", "github", "repo")
            written[column] = str(values["repository"] or "")
        if "path" in values:
            written[_column(page, "Path", "path")] = str(values["path"] or "")
        if values.get("kind") == "document":
            written[_column(page, *creation.COLUMNS["repository"])] = ""
            written[_column(page, *creation.COLUMNS["path"])] = ""
        elif values.get("kind") == "code":
            kept = {
                key: str(values[key] or "").strip()
                if key in values
                else _first(page, *creation.COLUMNS[key])
                for key in ("repository", "path")
            }
            if not any(kept.values()):
                raise ValueError(self.runner.voice.say("project-needs-repository"))
        if "description" in values:
            description = " ".join(str(values["description"] or "").split())
            written[_column(page, *creation.COLUMNS["description"])] = description
        if "site" in values:
            site = str(values["site"] or "").strip()
            if site and not creation.is_site(site):
                raise ValueError(self.runner.voice.say("project-site-invalid", given=site))
            written[_column(page, *creation.COLUMNS["site"])] = site
        if str(values.get("name", "")).strip():
            written[self.runner.client.title_property(database)] = str(values["name"]).strip()
        if not written and "content" not in values:
            raise ValueError("nothing to change")
        if "content" in values:
            self._guard_brief(page_id, values)
        if written:
            self.runner.client.update(database, page_id, written)
        # Replacing, not appending: the brief is a value. See `save_context`,
        # which is the same gesture on the one page above all projects.
        if "content" in values:
            self.runner.client.replace_markdown(page_id, str(values["content"]))
        # The index is kept for ten minutes, and a rename that took that long to
        # show would be a rename somebody made twice.
        self._projects = {}
        self._projects_at = 0.0
        self.hub.publish("projects", saved=page_id)
        return self.project(page_id)

    def _guard_brief(self, page_id: str, values: dict) -> None:
        """Refuse a brief that would overwrite what it was not written from.

        Two refusals, both only asked for by a caller that says what it saw. A
        `base` — the `version` it opened the brief at — that the page no longer
        has is a conflict (409: somebody wrote to it in Notion meanwhile). And
        a page that holds what Markdown cannot is rewritten only once the caller
        says it knows (`accept_losses`), so that nothing a page holds goes
        without having been shown. A caller that sends neither, like the edit
        form, keeps the plain replacement it always had.
        """
        client = self.runner.client
        if "base" in values and _digest(client.blocks_text(page_id)) != values["base"]:
            raise RuntimeError("this brief changed in the board since it was opened")
        if "base" in values and not values.get("accept_losses"):
            if client.losses(page_id):
                raise ValueError(
                    "this brief holds what Markdown cannot keep; saving it would lose it"
                )

    def set_picture(self, page_id: str, slot: str, picture: store.Picture) -> dict:
        """Change a project's cover or icon, and say where that leaves it.

        Shown here at once, whatever the board says: what it refused stays
        pending, with the reason, and is sent again at the next reading of the
        projects. Which is why the answer is the two pictures and not the whole
        project — rereading the page is exactly what a board that is not
        answering would refuse too.
        """
        if slot not in store.SLOTS:
            raise ValueError(f"a project has a cover and an icon, not a {slot}")
        if not self.runner.workspace.projects:
            raise ValueError("this workspace has no projects database")
        bare = page_id.replace("-", "")
        client = self.runner.client
        self.images.change(
            bare, slot, picture, lambda which, chosen: client.set_picture(bare, which, chosen)
        )
        shown = self._shown(bare)
        for row in self._projects.values():
            if row["id"] == bare:
                row.update(shown)
        self.hub.publish("projects", saved=bare)
        return {"id": bare, **shown}

    def picture(self, page_id: str, slot: str) -> tuple[bytes, str]:
        """The bytes of a project's picture, from this machine's copy.

        Never a redirect to where the board keeps it: a Notion file's URL is
        good for an hour, and a console left open is open longer than that.
        """
        if slot not in store.SLOTS:
            raise LookupError(f"a project has a cover and an icon, not a {slot}")
        return self.images.picture(page_id, slot, lambda: self.runner.client.page(page_id))

    # -- the standing context -------------------------------------------------

    def context(self) -> dict:
        """What reaches every ticket before the ticket itself does.

        Read as text rather than as blocks, which is what the runner puts in the
        prompt anyway — so what this pane shows is exactly what an agent is told,
        and editing it here is editing that.
        """
        space = self.runner.workspace
        return {
            "text": space.context,
            "page": space.context_page,
            "where": self.config.notion.page("context"),
            "storage": self.config.storage.mode,
            # No page to write to is not an error, it is a workspace without a
            # context row — the pane says so rather than offering a save button
            # that could only fail.
            "editable": bool(space.context_page),
        }

    def save_context(self, text: str) -> dict:
        """Rewrite the standing context. The one page the console replaces.

        Replacing, not appending: this is a value, not a history — saving it
        twice must leave one text, not two copies of it under each other. Every
        other write in this console appends, and for the opposite reason.
        """
        space = self.runner.workspace
        if not space.context_page:
            raise ValueError(
                f"this workspace has no “{self.config.notion.page('context')}” page to write to"
            )
        self.runner.client.replace_markdown(space.context_page, text)
        # The workspace was resolved with the old text in it.
        self.forget()
        self.hub.publish("context", saved=True)
        return {"ok": True, "text": text.strip()}

    # -- what comes back on its own, as something you can change --------------

    def save_schedule(self, page_id: str, values: dict) -> dict:
        """Change one row of the Schedules database from the console.

        Only the columns a schedule is *written* in — the cadence, the hour,
        the day, the tick, and the five a ticket inherits. Never `Next`
        or `Last`: those are what a pass writes back, and a console that let you
        edit them would let you make an occurrence happen twice.
        """
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        settings = self.config.notion
        writable = {
            "cadence": settings.prop("cadence"),
            "at": settings.prop("at"),
            "day": settings.prop("day"),
            "active": settings.prop("active"),
            "model": settings.prop("model"),
            "priority": settings.prop("priority"),
        }
        written: dict[str, Any] = {}
        for key, name in writable.items():
            if key not in values:
                continue
            value = values[key]
            if key == "active":
                written[name] = bool(value)
            elif key == "priority":
                # A score, refused outside 0–100; empty is the middle one.
                written[name] = priority_module.cell(
                    priority_module.given(value), self._schedule_column(name)
                )
            else:
                written[name] = str(value or "")
        # A type and a sub-type said by their keys, as a new ticket's are, and
        # written as the board spells them: the ticket is born with that word.
        if "type" in values:
            kind = str(values["type"] or "").strip()
            if kind and kind not in kinds_module.KINDS:
                raise ValueError(f"unknown type “{kind}”")
            written[settings.prop("type")] = self.runner.kind_name(kind) if kind else ""
        if "subtype" in values:
            subtype = str(values["subtype"] or "").strip()
            if subtype and subtype not in subtypes.KEYS:
                raise ValueError(f"unknown sub-type “{subtype}”")
            written[settings.prop("subtype")] = subtypes.option(subtype) if subtype else ""
        if "project" in values:
            written[settings.prop("project")] = [values["project"]] if values["project"] else []
        if "name" in values and str(values["name"]).strip():
            written[self.runner.client.title_property(database)] = str(values["name"]).strip()
        if not written and "body" not in values:
            raise ValueError("nothing to change")
        if written:
            self.runner.client.update(database, page_id, written)
        # Replacing, not appending: the body is the brief every occurrence is
        # born with, a value like a project's. See `save_project`.
        if "body" in values:
            self.runner.client.replace_markdown(page_id, str(values["body"]))
        self.hub.publish("schedules", saved=page_id)
        return {"id": page_id.replace("-", "")}

    def create_schedule(self, name: str, values: dict) -> dict:
        """A new row in the Schedules database, left unticked.

        Unticked deliberately, whatever the form said: a schedule that starts
        producing tickets the second it is typed is a schedule nobody dares
        write. You look at it, then you turn it on.
        """
        name = str(name).strip()
        if not name:
            raise ValueError("a schedule needs a name")
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        page_id = self.runner.client.create_row(
            database, name, {self.config.notion.prop("active"): False}
        )
        self.save_schedule(page_id, {**values, "active": False})
        return {"id": page_id.replace("-", ""), "name": name}

    def launch_schedule(self, page_id: str) -> dict:
        """Run one schedule now, once however many times the button is pressed.

        A second request for a schedule already being launched is refused rather
        than queued: it is the double click, and it must not make a second ticket.
        """
        wanted = page_id.replace("-", "")
        with self._launch_guard:
            if wanted in self._launching:
                raise RuntimeError("this schedule is already being launched")
            self._launching.add(wanted)
        try:
            entry = self.runner.launch(wanted)
        except store.StoreError:
            self.forget()
            raise
        finally:
            with self._launch_guard:
                self._launching.discard(wanted)
        self.hub.publish("schedules", launched=wanted)
        return {"ticket": entry["id"], "title": entry["ticket"]}

    def schedules(self) -> dict:
        """What comes back on its own, as `ponos schedules` says it.

        Read when the page is opened rather than watched like the board: a
        schedule moves four times a day at the very most, and a console polling
        that database would be asking Notion a question whose answer has not
        changed since breakfast.

        Two facts travel with the rows, because a list of schedules that all
        look fine explains nothing on an installation where none of them fire:
        whether the workspace has the database at all, and whether
        `runner.schedule` is on.
        """
        try:
            rows = self.runner.schedules()
            database = bool(self.runner.workspace.schedules)
        except store.StoreError:
            self.forget()
            raise
        # The names the board has already read, and no more: a projects cache
        # gone cold is a query the rows do not have to wait for. A row whose
        # project is not in it still carries the page it points at, and the
        # console writes the name in once its list of projects arrives.
        projects = self._projects
        return {
            "enabled": self.config.runner.schedule,
            # The zone the hours are said in, for the calendar to lay them out in.
            "timezone": schedules_module.timezone_name(),
            "database": database,
            "page": self.config.notion.page("schedules"),
            # Which board: "a row in the database" is Notion's sentence, and a
            # Markdown board has files.
            "storage": self.config.storage.mode,
            "schedules": [self._schedule(row, projects) for row in rows],
            # What the form offers for the type and the sub-type, only where the
            # Schedules database has the column: a value for a missing one would
            # be dropped on its way in. `ponos init` adds them.
            "choices": self._schedule_choices(),
        }

    def _schedule_column(self, name: str) -> str | None:
        """The kind of one column of the Schedules database, None when it has none."""
        database = self.runner.workspace.schedules
        try:
            return self.runner.client.schema(database).get(name) if database else None
        except store.StoreError:
            return None

    def _schedule_choices(self) -> dict[str, list[dict[str, str]]]:
        database = self.runner.workspace.schedules
        try:
            schema = self.runner.client.schema(database) if database else {}
        except store.StoreError:
            return {}
        settings = self.config.notion
        choices: dict[str, list[dict[str, str]]] = {}
        if settings.prop("type") in schema:
            choices["type"] = [
                {"value": key, "label": self.runner.kind_name(key)} for key in kinds_module.KINDS
            ]
        if settings.prop("subtype") in schema:
            choices["subtype"] = [
                {"value": subtype.key, "label": subtype.label} for subtype in subtypes.SUBTYPES
            ]
        return choices

    def schedule(self, page_id: str) -> dict:
        """One schedule, as the list says it, plus what is written on its page.

        The body is what the list leaves out, and it is the part that matters:
        it is copied under every ticket the schedule makes. Read here, once,
        rather than with every row — a list of twenty schedules would otherwise
        be twenty pages read to draw a table that shows none of them.
        """
        wanted = page_id.replace("-", "")
        row = next((item for item in self.schedules()["schedules"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no schedule with id {wanted}")
        return {**row, "body": self.runner.client.blocks_text(page_id)}

    def _schedule(self, schedule: schedules_module.Schedule, projects: dict) -> dict:
        """One row of the Schedules database, as the pane reads it.

        Left in the order Notion hands them over — that order is somebody's, and
        a console that sorted it would be rearranging their page for them.
        """
        next_at = schedules_module.upcoming(schedule, datetime.now().astimezone())
        return {
            "id": schedule.page.id.replace("-", ""),
            "name": schedule.name,
            "url": schedule.page.url,
            "cadence": schedule.cadence,
            "at": schedule.at,
            "day": schedule.day,
            "active": schedule.active,
            # When the next ticket is born, not where the pass left its
            # bookmark: a schedule turned off has none, and one that is due has
            # it now. See `schedules.upcoming`.
            "next": next_at.isoformat(timespec="minutes") if next_at else "",
            "last": schedule.last.isoformat(timespec="minutes") if schedule.last else "",
            # The ticket the last occurrence made, addressed the way the board
            # addresses one: the console links to its page, not to Notion's.
            "ticket": schedule.last_ticket.replace("-", ""),
            "project": (projects.get(schedule.project) or {}).get("name", ""),
            "project_id": schedule.project.replace("-", ""),
            "model": schedule.model,
            "priority": schedule.priority,
            # By their keys, as the form sends them back: `code`, `bug`.
            "type": self.config.notion.kind_of(schedule.kind),
            "subtype": subtypes.of(schedule.subtype),
            "problem": schedule.problem,
        }

    def state(self, local: bool = True) -> dict:
        """Everything the header shows: the timer, the lock, the version, the spend.

        `local`: whether the page asking is on this machine, which is where an
        update can be started from — see `upgrade.Upgrade.offer`.
        """
        configuration = self.config
        held = state.running()
        entries = state.history(10_000)
        # A timer that is on and a board that does not move is the one state
        # somebody would open a terminal for. `credits` is 0 the rest of the
        # time, which is how the header knows to say nothing.
        # The reserve counts as being out of credit here, and deliberately so:
        # to whoever is looking at the header, "nothing is being started and
        # here is when that changes" is one state, not two.
        waiting = (
            credits.held() or credits.held(what="reserve")
            if configuration.runner.wait_for_credits
            else 0.0
        )
        budget_limit = configuration.budget.daily_usd
        budget_spent = state.spent_today() if budget_limit > 0 else 0.0
        version = update_module.running()
        return {
            # In a container the timer is the image's `ponos run --every`, which
            # starts with it and stops with it: on for as long as this answers.
            "timer": "enabled" if config_module.in_container() else systemd.read().label,
            "running": bool(held),
            "lock": held,
            # The sessions in flight, read from their logs: what a page that has
            # just been reloaded counts before the stream has said a word.
            "sessions": live.active(held=lambda: held),
            "credits": waiting,
            "credits_at": credits.when(waiting) if waiting else "",
            # The day's spending limit, once reached: asked of the history
            # rather than of the note a run writes, so that the banner is there
            # the moment the figure crosses the line, not at the next pass.
            "budget": budget_limit if budget_spent >= budget_limit > 0 else 0.0,
            "budget_spent": round(budget_spent, 2),
            "workspace_root": str(configuration.runner.workspace_root),
            # Which board this console is looking at. The panes read it to know
            # whether a Notion link is worth drawing, and whether the sync has
            # anything to say — in `markdown` mode neither does.
            "storage": configuration.storage.mode,
            "board_path": str(configuration.storage.path) if configuration.storage.markdown else "",
            "interval_seconds": configuration.runner.interval_seconds,
            "model": configuration.runner.model or "default",
            "permission_mode": configuration.runner.permission_mode,
            "claude": bool(session.available()),
            "version": version["version"],
            # What the version's tooltip says: the commit it was made of.
            "commit": {key: version[key] for key in ("commit", "date", "subject")},
            "update": _update_available(),
            "upgrade": self.upgrade.offer(local),
            "spend": round(sum(float(entry.get("cost_usd") or 0) for entry in entries), 2),
            "handled": len(entries),
            "chat": self.chat.state(),
            "commands": sorted(self.commands.allowed),
            "busy": self.commands.busy,
        }

    def statistics(self, start: str = "", end: str = "", project: str | None = None) -> dict:
        """The statistics page: the board, dated with the runner's history.

        See `statistics` for which of the two says when a ticket closed. With a
        `project`, its page's: the same figures over that project's tickets.
        """
        first, last = statistics.period(start, end, datetime.now().date())
        tickets = self.board()["tickets"]
        return statistics.figures(
            tickets,
            state.history(1_000_000),
            first,
            last,
            project=project,
            kind_of=self.config.notion.kind_of,
        )

    def disk(self, *, fresh: bool = False) -> dict:
        """The room the runner takes on this machine, and what keeps it in check."""
        held = getattr(self, "_disk", None)
        if fresh or held is None or time.time() - held[0] > DISK_TTL:
            worktrees = cleanup.worktree_sizes()
            sizes = cleanup.sizes({"worktrees": sum(size for _, size in worktrees)})
            held = (time.time(), sizes, worktrees)
            self._disk = held
        measured, sizes, worktrees = held
        settings = self.config.runner
        # Read every time, unlike the sizes: it is one call, and a console that
        # says the disk has room when it just filled up is worse than none.
        room = resources.disk_mb(config_module.state_dir())
        free = room[0] if room else None
        return {
            "sizes": sizes,
            "worktrees": [{"name": name, "size": size} for name, size in worktrees[:20]],
            "free_mb": free,
            "disk_mb": room[1] if room else None,
            "min_free_disk_mb": settings.min_free_disk_mb,
            "short": resources.short_of_disk(settings.min_free_disk_mb, config_module.state_dir())
            is not None,
            "stale_worktree_days": settings.stale_worktree_days,
            "total": sum(sizes.values()),
            "measured_at": datetime.fromtimestamp(measured, UTC).isoformat(),
            "tidied_at": (
                datetime.fromtimestamp(cleanup.tidied_at(), UTC).isoformat()
                if cleanup.tidied_at()
                else ""
            ),
            "retention_days": settings.log_retention_days,
            "clean_done_worktrees": settings.clean_done_worktrees,
        }

    def health(self) -> dict:
        """What is wrong with the installation, for the top of the dashboard. See `health.py`."""
        checks = health.run(self.config, self.runner.client)
        return {
            "checks": [check.asdict() for check in checks],
            "problems": health.problems(checks),
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def fix_health(self, payload: dict) -> dict:
        """One fix a check offered, once the page says it was confirmed."""
        if payload.get("confirmed") is not True:
            raise ValueError("a fix is made only once it is confirmed")
        done = health.fix(
            self.config,
            self.runner.client,
            str(payload.get("action") or ""),
            str(payload.get("target") or ""),
            confirmed=True,
        )
        # The board's shape just changed under the cache that reads it.
        self.forget_projects()
        return {"done": done, **self.health()}

    def clean(self) -> dict:
        """The daily tidy, now. Under the run lock, or refused while a run holds
        it — the worktrees a session stands in are the ones it would weigh."""
        try:
            with state.lock():
                tidied = self.runner.tidy(now=True)
        except state.Busy as error:
            raise RuntimeError("a run is in progress — try again once it has finished") from error
        return {
            "removed": len(tidied.removed) if tidied else 0,
            "logs": tidied.logs if tidied else 0,
            "freed": tidied.freed if tidied else 0,
            **self.disk(fresh=True),
        }

    def history(self, limit: int = 30) -> dict:
        return {"entries": list(reversed(state.history(limit)))}

    def logs(self, ticket: str = "") -> dict:
        """The newest session logs — of one ticket, when it is named.

        Named by its short id, as the file is: a ticket opened on the console
        finds its last session here, however many others ran since.
        """
        paths = sorted(state.logs_dir().glob("*.jsonl"), reverse=True)
        if ticket:
            paths = [path for path in paths if path.stem.rsplit("-", 1)[-1] == ticket]
        paths = paths[:40]
        return {
            "logs": [
                {
                    "name": path.name,
                    "ticket": path.name.removesuffix(".jsonl").rsplit("-", 1)[-1],
                    "at": path.stat().st_mtime,
                    "size": path.stat().st_size,
                }
                for path in paths
                if path.exists()
            ]
        }

    def log(self, name: str) -> dict:
        """One session, as the steps it was made of. Never as a path from outside."""
        target = state.logs_dir() / Path(name).name
        if not target.exists() or target.suffix != ".jsonl":
            raise LookupError(f"no such log: {name}")
        steps = []
        with target.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                for step in live.steps(line):
                    steps.append({"label": step.label, "detail": step.detail, "said": step.said})
        # The count is of the whole session, the steps only of its end: a card
        # says how far a run has come, and a thousand lines is enough to read.
        return {"name": target.name, "count": len(steps), "steps": steps[-1000:]}

    def service_log(self, lines: int = 500) -> dict:
        """The end of ponos.log — the runner's and the console's own journal, masked.

        What `ponos logs --service` prints, for whoever has no terminal at hand:
        the last lines, never the whole file. See log.py.
        """
        return {"path": str(log.path()), "lines": log.tail(max(1, min(lines, 2000)))}

    def runs(self, page_id: str) -> dict:
        """Every run of one ticket the local journal holds, newest first.

        Read from the database, not from the page: the page keeps what the
        agent said, the journal every step — and every run, where the page
        and the logs only ever knew the last one by name. See journal.py.
        """
        return {
            "runs": [
                {**run, "model_label": models.label(run.get("reported") or run.get("model") or "")}
                for run in journal.runs(page_id)
            ]
        }

    def run_steps(
        self, identifier: int, before: int = 0, after: int = 0, limit: int = journal.PAGE
    ) -> dict:
        """One page of a run's steps: its end, what came before `before`, or after `after`."""
        found = journal.run(identifier)
        if found is None:
            raise LookupError(f"no such run: {identifier}")
        return {
            **journal.steps(identifier, before=before, after=after, limit=limit),
            "ended": bool(found["ended_at"]),
        }

    def talk(self, page_id: str) -> dict:
        """What has been said on one ticket, oldest first.

        This is the ticket's terminal, and it is not a new place to talk: it is
        the discussion Notion already holds, read as a conversation. An answer
        relayed from a phone — or from this console — wears the runner's token
        and is nonetheless yours, so it is shown under your name and without the
        line that says which device it came through.

        `waiting` says whether the ticket is waiting on you: the last word on
        the page is a question a run asked, and nobody has answered it yet. The
        page opens on the discussion when it is, rather than leave the reader to
        guess that there is one.
        """
        me = self.runner.myself()
        comments = self.runner.client.comments(page_id)
        messages = [
            {
                "role": _voice(comment, me),
                "text": conversation.said(comment.text),
                "at": comment.created_time,
            }
            for comment in comments
        ]
        last = messages[-1] if messages else None
        return {
            "id": page_id,
            "mention": self.config.notion.mention or conversation.MENTION,
            "messages": messages,
            "waiting": bool(
                last
                and last["role"] == "runner"
                and last["text"].lstrip().startswith(voice.MARKS["blocked"])
            ),
        }

    # -- writing --------------------------------------------------------------

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
    ) -> dict:
        title = title.strip()
        if not title:
            raise ValueError("a ticket needs a title")
        kind = kind.strip()
        if kind and kind not in kinds_module.KINDS:
            raise ValueError(f"unknown type “{kind}”")
        score = priority_module.given(priority)
        subtype = subtype.strip()
        if subtype and subtype not in subtypes.KEYS:
            raise ValueError(f"unknown sub-type “{subtype}”")
        settings = self.config.notion
        values: dict[str, Any] = {}
        # Ready means "start it now"; anything else means the ticket is being
        # written. A draft goes where the board keeps its drafts, when the
        # configuration names that option, and is otherwise left with no
        # status rather than parked in a column nobody named: the runner claims
        # what it was told to claim, and a console that invented a column would
        # be inventing a workflow.
        if ready:
            values[settings.prop("status")] = settings.state("ready")
        elif _draft(settings):
            values[settings.prop("status")] = _draft(settings)
        if project:
            values[settings.prop("project")] = [project]
        # The score always, 50 when none is said, wherever the board has the
        # column: the card says where the ticket stands in the queue rather
        # than leave it to an empty cell.
        if self._scored():
            values[settings.prop("priority")] = self.runner.priority_cell(score)
        # Each one left out when it is not said: an empty type is the runner's
        # to classify before the ticket runs, as on a ticket written in Notion.
        if kind:
            values[settings.prop("type")] = self.runner.kind_name(kind)
        # Ignored on a ticket of another type, as on the board — but written:
        # a type left empty may well turn out to be code.
        if subtype and kind in ("", "code"):
            values[settings.prop("subtype")] = subtypes.option(subtype)
        if model.strip():
            values[settings.prop("model")] = model.strip()
        if on.strip():
            values[settings.prop("on")] = on.strip()
        page_id = self.runner.client.create_row(self.runner.database, title, values)
        if body.strip():
            self.runner.client.append_markdown(page_id, body)
        self.watch.nudge()
        return {"id": page_id, "title": title}

    def set_on(self, page_id: str, prompt: str) -> dict:
        """Write the prompt a ticket runs at each change of its status; empty removes it.

        Straight to the board and not through the outbox: the outbox is about a
        status moving under a card, and a prompt is a value nobody else is
        writing at the same time.
        """
        settings = self.config.notion
        name = settings.prop("on")
        if name not in self.runner.client.schema(self.runner.database):
            raise ValueError(f"this board has no “{name}” column: run `ponos init` to add it")
        self.runner.client.update(self.runner.database, page_id, {name: prompt.strip()})
        return {"id": page_id.replace("-", ""), "on": prompt.strip()}

    def transitions(self, page_id: str) -> dict:
        """The executions of one ticket's « On » prompt, newest first."""
        return {"transitions": transitions_module.history(page_id)}

    def set_status(self, page_id: str, key: str, seen: str | None = None) -> dict:
        """Move a ticket: queued now, in Notion as soon as Notion takes it.

        `seen` is the status the card showed when it was moved. A page that says
        anything else by the time the write goes out was moved in Notion
        meanwhile, and is left as it is — see `board.send`. A caller that does
        not say is taken to mean the status the console last read.
        """
        if key not in _keys(self.config.notion):
            raise ValueError(f"unknown column “{key}”")
        settings = self.config.notion
        if key == "cancelled" and not self._cancels():
            raise ValueError(
                f"this board has no “{settings.state('cancelled')}” option to cancel a ticket into"
            )
        status = _status(settings, key)
        held = self.reader.get(page_id)
        if seen is None:
            seen = str(store.read(held, settings.prop("status")) or "") if held else ""
        self.outbox.put(
            board_module.Write(
                page=page_id.replace("-", ""),
                column=key,
                status=status,
                seen=seen,
                title=held.title if held else "",
            )
        )
        self.watch.nudge()
        return {"id": page_id, "status": status, "sync": "pending"}

    def _send(self, write: board_module.Write) -> store.Page:
        """One attempt at one queued move, and the page it left, held."""
        page = board_module.send(
            self.runner.client, self.runner.database, self.config.notion.prop("status"), write
        )
        self.reader.hold(page)
        return page

    def tell(self, page_id: str, text: str) -> dict:
        """Say something to a ticket, as a comment on it.

        Which is already how a ticket is answered: a run that ends `blocked`
        leaves its question on the page, the reply underneath puts the ticket
        back in the queue, and a reply that names the runner asks it for words
        instead. The console types into that, rather than beside it.

        Two things make it work. It goes **into the thread the runner last spoke
        in**, so it sits under the question and so the next pass finds a thread
        it is part of. And it opens with `conversation.RELAYED`, because the only
        Notion token this console has is the runner's own: without that line the
        next run would read its own voice, and answer itself forever.

        A password or a token in it never reaches the page: it is masked here,
        before the comment, the stream or anything else sees it — see
        `redaction`.
        """
        text = redaction.masked(text.strip())
        if not text:
            raise ValueError("nothing to say")
        me = self.runner.myself()
        comments = self.runner.client.comments(page_id)
        said = self.runner.voice
        relayed = said.say("relayed", channel=said.say("relayed-console"))
        # Read against the question the ticket is waiting on, like an answer
        # from a phone: “2” lands as the option it names.
        # The message itself keeps its lines, which a phone's never had.
        asked = question.waiting(comment.text for comment in comments)
        lines = channels.spelled(text, said, asked) if asked else [text]
        if lines and lines[-1] == " ".join(text.split()):
            lines[-1] = text
        self.runner.client.comment(
            page_id, "\n".join([f"{relayed}.", *lines]), _thread(comments, me)
        )
        self.runner.forget_comments(page_id)
        message = {
            "role": "you",
            "text": text,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.hub.publish("talk", ticket=page_id, **message)
        return message

    # -- deciding -------------------------------------------------------------

    def decision(self, page_id: str) -> dict:
        """What a card waiting on you offers: why it waits, and what to do about it.

        A blocked ticket says why it stopped, what is done and what would get it
        moving; one in review says what it brought back, where its checks stand
        and what it could not check — see decisions.py. Read off the last report
        on the page, so a ticket blocked before the reports named their kind of
        stop reads the same, guessed from its words.
        """
        page, column, comments = self._waiting(page_id)
        settings = self.config.notion
        said = self.runner.voice
        if column == "review":
            found = decisions.delivered(comment.text for comment in comments)
            url = found.pull_request or str(store.read(page, settings.prop("pull_request")) or "")
            # Asked of GitHub when the panel opens, not kept: a check that went
            # green a minute ago is the thing this panel exists to say.
            listed = git.checks(url, self.config.github, timeout=20) if url else []
            state = decisions.checks_state(listed) if listed else ("unknown" if url else "none")
            failing = next(
                (check for check in listed if check.get("bucket") in ("fail", "cancel")), None
            )
            solutions = decisions.deciding(
                found, said, checks=state, validate=self._validates(), cancel=self._cancels()
            )
            return {
                "id": page.id.replace("-", ""),
                "column": column,
                "summary": found.summary,
                "facts": found.facts,
                "pull_request": url,
                "checks": {
                    "state": state,
                    "link": str((failing or {}).get("link") or "")
                    or (f"{url}/checks" if url else ""),
                    "listed": [
                        {
                            "name": str(check.get("name") or ""),
                            "bucket": str(check.get("bucket") or ""),
                            "link": str(check.get("link") or ""),
                        }
                        for check in listed
                    ],
                },
                "caveats": found.caveats,
                "solutions": self._offered(solutions),
            }
        found = decisions.blockage(comment.text for comment in comments)
        solutions = decisions.unblocking(found, models=self._has("model"), cancel=self._cancels())
        asked = found.question
        return {
            "id": page.id.replace("-", ""),
            "column": column,
            "category": found.category,
            "declared": found.declared,
            "reported": found.reported,
            "reason": found.reason,
            "done": found.done,
            "detail": found.detail,
            "question": (
                {"ask": asked.ask, "mode": asked.mode, "options": asked.options} if asked else None
            ),
            "model": str(store.read(page, settings.prop("model")) or ""),
            "solutions": self._offered(solutions),
        }

    def decide(
        self,
        page_id: str,
        key: str,
        *,
        number: int = 0,
        text: str = "",
        model: str = "",
        titles: list[str] | None = None,
        channel: str = "",
    ) -> dict:
        """Do one of the things `decision` offered, and say so on the ticket.

        The comment comes first when the ticket goes back to work, so that the
        session the move starts reads the instruction; it comes last when the
        ticket is filed away, and that move is made at once rather than queued,
        because a comment under a blocked ticket is an answer — the runner would
        wake it up before the queued move reached the board. `channel` is where
        the choice came from, said on the comment: the console, unless named.
        """
        page, column, comments = self._waiting(page_id)
        settings = self.config.notion
        said = self.runner.voice
        if column == "review":
            solutions = decisions.deciding(
                decisions.delivered(comment.text for comment in comments),
                said,
                checks="failed",
                validate=self._validates(),
                cancel=self._cancels(),
            )
        else:
            solutions = decisions.unblocking(
                decisions.blockage(comment.text for comment in comments),
                models=self._has("model"),
                cancel=self._cancels(),
            )
        solution = next(
            (
                offered
                for offered in solutions
                if offered.key == key
                and (key not in ("option", "caveat") or offered.number == number)
            ),
            None,
        )
        if solution is None:
            raise ValueError(f"“{key}” is not something this ticket offers")
        text = redaction.masked(str(text or "").strip())
        named = [title.strip() for title in titles or [] if title.strip()]
        if solution.needs == "text" and not text:
            raise ValueError("this choice needs an instruction")
        if solution.needs == "model" and not model.strip():
            raise ValueError("choose a model")
        if solution.needs == "titles" and not named:
            raise ValueError("name at least one ticket")
        if solution.key == "model":
            if not self._has("model"):
                raise ValueError("this board has no Model column")
            self.runner.client.update(
                self.runner.database, page.id, {settings.prop("model"): model.strip()}
            )
        created = []
        if solution.key == "split":
            relation = store.read(page, settings.prop("project")) or []
            told = said.say("told-split", title=page.title, url=page.url)
            created = [
                self.create_ticket(title, told, relation[0] if relation else "", ready=False)
                for title in named
            ]
        relayed = said.say("relayed", channel=channel or said.say("relayed-console"))
        lines = [
            f"{relayed}.",
            *decisions.told(said, solution, text, model=model.strip(), titles=named),
        ]
        seen = str(store.read(page, settings.prop("status")) or "")
        if solution.column == "ready":
            self._say_on(page_id, lines, comments)
            moved = self.set_status(page_id, "ready", seen)
        else:
            if column == "blocked":
                try:
                    self._send(
                        board_module.Write(
                            page=page.id.replace("-", ""),
                            column=solution.column,
                            status=_status(settings, solution.column),
                            seen=seen,
                            title=page.title,
                        )
                    )
                except board_module.Conflict as moved_since:
                    raise ValueError(
                        f"the ticket was moved meanwhile, to {moved_since}"
                    ) from moved_since
                moved = {"id": page_id, "status": _status(settings, solution.column)}
            else:
                moved = self.set_status(page_id, solution.column, seen)
            self._say_on(page_id, lines, comments)
        self.watch.nudge()
        return {
            **moved,
            "column": solution.column,
            "told": lines[1:],
            "created": [ticket["id"] for ticket in created],
        }

    def _waiting(self, page_id: str) -> tuple[store.Page, str, list[store.Comment]]:
        """A card that waits on you: its page, its column, what was said on it."""
        settings = self.config.notion
        page = self.reader.get(page_id) or self.runner.client.page(page_id)
        status = str(store.read(page, settings.prop("status")) or "")
        column = _columns(settings).get(status, "draft")
        if column not in ("blocked", "review"):
            raise ValueError(
                f"only a blocked ticket or one in review waits on a decision, not {column}"
            )
        return page, column, self.runner.client.comments(page_id)

    def _say_on(self, page_id: str, lines: list[str], comments: list[store.Comment]) -> None:
        """A decision, written where an answer typed at the ticket would go — see `tell`."""
        thread = _thread(comments, self.runner.myself())
        self.runner.client.comment(page_id, "\n".join(lines), thread)
        self.runner.forget_comments(page_id)
        self.hub.publish(
            "talk",
            ticket=page_id,
            role="you",
            text="\n".join(lines[1:]),
            at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def _offered(self, solutions: list[decisions.Solution]) -> list[dict]:
        said = self.runner.voice
        return [
            {**solution.as_dict(), "label": decisions.label(said, solution)}
            for solution in solutions
        ]

    def _cancels(self) -> bool:
        """Whether this board has a cancelled column of its own — see `cancelled_column`."""
        try:
            return self.runner.cancelled_column()
        except store.StoreError:
            return False

    def _validates(self) -> bool:
        """Whether this board has a validated column the runner would honour."""
        try:
            return self.runner.validated_column()
        except store.StoreError:
            return False

    def _has(self, key: str) -> bool:
        """Whether the board has the column a setting names."""
        try:
            return self.config.notion.prop(key) in self.runner.client.schema(self.runner.database)
        except store.StoreError:
            return False

    # -- the configuration ----------------------------------------------------

    def settings(self) -> dict:
        """Every setting the file holds, as the console draws it — secrets aside.

        And the projects that decide their automatic validation for themselves,
        which the file does not hold but its validation card has to say: a
        switch that reads "on" is not the whole truth on those.
        """
        return {
            **settings_module.describe(self.config),
            "own_validation": project_settings.owning_validation(),
        }

    # -- a project's own settings -------------------------------------------

    def _validation_fields(self) -> list[dict]:
        """The global card's switches, as they are worded there — one source for both pages."""
        section = next(item for item in settings_module.SECTIONS if item.key == "validation")
        return [
            {
                "kind": field.key.removeprefix("force_validated_"),
                "name": field.name,
                "label": field.label,
                "help": field.help,
            }
            for field in section.fields
        ]

    def project_settings(self, page_id: str) -> dict:
        """What a project decides for itself, and what the file decides when it does not.

        `global` is what the runner would apply without the project's own
        switches — the file's, defaults included — so that a page can show it
        as it stands, and fill the project's in with it when they are turned on.
        """
        bare = project_settings.key(page_id)
        globally = {kind: self.config.runner.forces_validation(kind) for kind in kinds_module.KINDS}
        own = project_settings.validation(bare)
        return {
            "id": bare,
            "validation": {
                "own": own is not None,
                "values": own if own is not None else globally,
                "global": globally,
                "fields": self._validation_fields(),
            },
        }

    def save_project_settings(self, page_id: str, payload: dict) -> dict:
        """Give a project its own settings, or hand them back to the file.

        `validation.own` false forgets the project's switches; true keeps those
        sent, type by type, and a type left out is off — never the file's, which
        would make a project's choice change the day somebody edits config.toml.
        """
        bare = project_settings.key(page_id)
        validation = payload.get("validation")
        if not isinstance(validation, dict) or not isinstance(validation.get("own"), bool):
            raise ValueError("say whether the project has its own automatic validation")
        values = validation.get("values") or {}
        if not isinstance(values, dict) or any(
            kind not in kinds_module.KINDS or not isinstance(value, bool)
            for kind, value in values.items()
        ):
            raise ValueError("automatic validation is a switch for each type of ticket")
        try:
            row = next(
                (
                    item
                    for item in self.projects().values()
                    if project_settings.key(item["id"]) == bare
                ),
                None,
            )
        except store.StoreError:
            row = None
        name = str(row["name"]) if row else ""
        project_settings.set_validation(bare, name, values if validation["own"] else None)
        self.hub.publish("settings", project=bare)
        return self.project_settings(bare)

    def folder(self, typed: str) -> dict:
        """A folder of this machine, for a path field to pick a file or a folder from."""
        return settings_module.folder(typed)

    def save_settings(self, payload: dict) -> dict:
        """Write what the console changed, and pick the new file up at once.

        The caches go first because a saved token, workspace or property name is
        a different board: keeping the old client would have the console explain
        that the setting did not work.
        """
        result = settings_module.save(self.config, payload)
        if result["saved"]:
            self.forget()
            self.hub.publish("settings", saved=result["saved"])
            self.watch.nudge()
        return result

    # -- the chat's opening frame ---------------------------------------------

    def brief(self) -> str:
        """What the workspace conversation is told before your first sentence.

        Written once per conversation, not once per message: it costs two Notion
        reads, and repeating it every turn would spend them for a session that
        already remembers. What it carries is the frame — who you are, what the
        projects are, where they live — and one instruction that matters more
        than the rest: the board is changed through `ponos`, not by
        guessing at the Notion API.
        """
        configuration = self.config
        lines = [
            "You are the assistant of a ponos workspace, reached from its web console.",
            "Somebody is in front of you: answer them, ask when something is ambiguous.",
            "",
            "# Your workspace",
            "",
            f"- Repositories live under `{configuration.runner.workspace_root}`.",
            "- `ponos` is on your PATH. `ponos list`, `status`, `history`,",
            "  `projects`, `logs <id>` and `doctor` are how you look at the board;",
            "  `run` handles the ready tickets now.",
            "- The Notion board is the source of truth for tickets. Read it through the",
            "  `ponos` command rather than through the Notion API directly.",
            "- You are not inside a ticket: nothing here has a worktree, a branch or a",
            "  pull request waiting. Work that deserves those is work that deserves a",
            "  ticket — say so, and offer to create one.",
        ]
        try:
            context = self.runner.workspace.context.strip()
        except store.StoreError:
            context = ""
        projects = self.projects()
        if projects:
            lines += ["", "# Projects", ""]
            for project in sorted(projects.values(), key=lambda item: item["name"].lower()):
                lines.append(f"- **{project['name']}** — {project['kind']} work")
        if context:
            lines += ["", "# Who you are working for", "", context[:6000]]
        return "\n".join(lines)


def _first(page: store.Page, *names: str) -> str:
    """The first of those columns the page actually carries, as text.

    A project database is written by hand, so its columns are named by hand:
    "Repository", "repository", or the bare "github" the runner used to ask for.
    `projects.py` reads them the same way, for the same reason.
    """
    for name in names:
        value = store.read(page, name)
        if value not in (None, "", []):
            return str(value)
    return ""


def _column(page: store.Page, *names: str) -> str:
    """The first of those columns the page actually carries, by name.

    What `_first` reads, written back: a value goes to the column somebody
    filled in rather than to a second one beside it. A page carrying none of
    them is written under the first name, which is the one this project would
    have been given had it been created here.
    """
    lookup = {key.lower(): key for key in page.properties}
    for name in names:
        found = lookup.get(name.lower())
        if found is not None:
            return found
    return names[0]


def _voice(comment: store.Comment, me: str) -> str:
    """Who said this: the runner, or you.

    `conversation.ours` is the answer wherever Notion will say who we are. Where
    it will not — an integration without the *Read user information* capability —
    the mark a report opens with is enough to *read* a discussion. It is not
    enough to answer one, which is why `converse` stays silent in that case and
    this does not.
    """
    if me:
        return "runner" if conversation.ours(comment, me) else "you"
    return "runner" if voice.is_report(comment.text) else "you"


def _thread(comments: list[store.Comment], me: str) -> str:
    """The discussion a message typed at a ticket belongs in.

    The last one the runner has spoken in, which is where an answer to its
    question goes. On a page it has never spoken on there is no such thread, and
    on a board whose integration will not say who it is there is no telling —
    both open a discussion of their own, which is the honest thing to do.
    """
    for thread in reversed(conversation.threads(comments)):
        if thread.spoken_by(me) and thread.last.discussion_id:
            return thread.last.discussion_id
    return ""


def _session_id(value: str) -> str:
    """The identifier inside a Session cell, whichever shape the column has.

    A URL column holds `ponos://session/<id>?cwd=…`, a text column holds
    the bare ID. Both are the same session, and the console shows the same link.
    """
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        return value.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return value


def _digest(text: str) -> str:
    """A short name for a text, to tell whether it is still the one that was read."""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


def _columns(settings) -> dict[str, str]:
    """Which column each status is drawn in: the first that carries it.

    A board whose `blocked` and `failed` are one status draws one column for
    them — the first of the two, see `board` — and the tickets have to land in
    that one. A plain `{status: key}` kept the *last*, and every blocked ticket
    went to a `failed` column that was never drawn: three tickets Notion shows
    as blocked, and a console that showed none.

    A status none of them names — the draft's own, `draft`, included when the
    board does not name it — is a draft as well: the callers fall back on it.
    """
    names: dict[str, str] = {"": "draft"}
    for key in _keys(settings):
        names.setdefault(_status(settings, key), key)
    return names


def _keys(settings) -> tuple[str, ...]:
    """The columns this board draws: the drafts, then the runner's.

    A ticket with no status is a draft, so the drafts are always the first
    column, named or not — see `_draft`.
    """
    return ("draft", *COLUMNS)


def _causes(tickets: list[dict]) -> None:
    """The cause on every card that stopped, and on no other.

    The board's « Blocage » column first; the history's last code for the
    ticket when the board has no such column, or a stop written before it was
    there. A card that has left blocked or failed carries none: the cause was
    the last stop's, and it is not stopped any more.
    """
    codes: dict[str, str] | None = None
    for ticket in tickets:
        if ticket.get("column") not in ("blocked", "failed"):
            ticket["block"] = None
        elif ticket.get("block") is None:
            codes = state.causes() if codes is None else codes
            ticket["block"] = blocks.describe(codes.get(str(ticket.get("id", "")), ""))


def _times(tickets: list[dict]) -> None:
    """How long Ponos has worked on every card, from the journal's runs in one read.

    `None` on a card the journal has no run for — a ticket from before it, or
    one never taken: the console says « — » there rather than a zero.
    """
    spans = journal.spans() if len(tickets) != 1 else journal.spans(str(tickets[0].get("id", "")))
    for ticket in tickets:
        ticket["worktime"] = worktime.measure(
            spans.get(str(ticket.get("id", "")), []), str(ticket.get("column", ""))
        )


def _subtype(page: store.Page, settings) -> str:
    """A ticket's sub-type, from its column — or, on a code ticket, its title's prefix.

    The prefix is what the runner would have written, and what an old ticket
    never got: a done one is left unwritten by `ponos subtypes --backfill`,
    since an edit would move its closing date. Read here, it is counted all
    the same. Nothing for a ticket of another type, whatever it says.
    """
    kind = settings.kind_of(str(store.read(page, settings.prop("type")) or ""))
    if kind not in ("code", ""):
        return ""
    written = subtypes.of(store.read(page, settings.prop("subtype")))
    return written or (subtypes.from_prefix(page.title) if kind == "code" else "")


def _checks(tickets: list[dict]) -> None:
    """The state of the checks on every card whose pull request is being followed.

    Read from `ponos.db` in one go, never from GitHub: see `ci.py`. A card that
    is not in review, or whose pull request has no check, carries none.
    """
    rows = state.ci_rows()
    for ticket in tickets:
        row = rows.get(str(ticket.get("id", ""))) if ticket.get("column") == "review" else None
        ticket["ci"] = ci.read(row, str(ticket.get("pull_request") or ""))


def _status(settings, key: str) -> str:
    """What a column writes: the board's word for it, and for the drafts `_draft`'s."""
    return _draft(settings) if key == "draft" else settings.state(key)


def _draft(settings) -> str:
    """The status a draft is written with: the option the board already had, or none.

    `draft` is an option the board already had — see `Notion.state` — and it
    counts only when named apart from every status the runner moves a ticket
    through: a draft that is also `ready` is a ticket the runner takes, and
    calling its column "Draft" would be lying. Unnamed, a draft is a ticket
    with no status, and a move to the drafts clears it.
    """
    draft = settings.state("draft")
    return draft if draft and draft not in [settings.state(key) for key in COLUMNS] else ""


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


def _instant(stamp: str) -> float | None:
    """An ISO time as Notion writes it, in seconds — or None for one it did not write."""
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _update_available() -> str:
    """The commit waiting to be installed, or an empty string for "none".

    Read from the stamp a run already writes — never by asking the remote: the
    console redraws its header on every reconnection, and a `git fetch` behind
    that would be a fetch every time a laptop wakes up.
    """
    status = update_module.waiting()
    return status.latest[:8] if status.stale else ""


def _subcommands() -> tuple[str, ...]:
    from ..__main__ import subcommands

    return subcommands()
