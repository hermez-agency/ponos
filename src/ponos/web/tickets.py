"""The board and its tickets: reading them, opening one, writing one, moving one.

The chapter the console is mostly made of, and the one that holds the board to
Notion's word: a card is a row of the tickets database read as the runner reads
it, a ticket opened is its page flattened as a session would be given it, and
a move is a write queued for the same page — `board.py` says why it waits in a
queue rather than in the browser. Which columns are drawn, which choices a new
ticket is offered and which gestures a card offers are all read off the board
itself: a button for a column Notion does not have is a button that fails.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import (
    blocks,
    ci,
    credits,
    git,
    journal,
    models,
    provision,
    session,
    state,
    stopping,
    store,
    subtypes,
    sync,
    systemd,
    worktime,
)
from .. import config as config_module
from .. import goals as goals_module
from .. import kinds as kinds_module
from .. import priority as priority_module
from .. import transitions as transitions_module
from ..config import Notion, state_dir
from ..schedules import scheduled_for
from ..ticket import short_id
from . import board as board_module
from . import live
from .base import Base

# And the board's own shape on the same cadence, for the same reason: the Notion
# client caches a database for its lifetime, which for the console is days. A
# column added in Notion — the validated one, most of all — has to appear
# without anyone restarting anything.
SCHEMA_TTL = 600

logger = logging.getLogger(__name__)

# How long a pause or an abandon waits for the run to say the session is gone.
# The session is given its grace to end on SIGTERM, then its containers are
# taken down: a minute covers a slow one, and a run that is not there costs
# nothing because it is not waited for.
STOP_WAIT_SECONDS = 60


# How many ticket pages are kept, read, while their `last_edited_time` holds.
# A ticket's page is a dozen block requests away — one to three seconds — and
# opening a ticket read it again every time. Enough for every ticket somebody
# opens in a day; the oldest goes first.
BRIEFS = 200


# The columns, in the order they are meant to be read. Anything the board
# carries that is none of them is a draft, so it is never hidden. The drafts
# come before them, whether or not the board names its own — see `_keys`.
# Blocked follows running: a ticket waiting on an answer is a ticket in
# progress that stopped, so it is read next to it, and so is paused, which is
# one that you stopped. Cancelled closes the row, beside done: the two ends a
# ticket can come to. This is the one order — the console, the filters and the
# MCP tools all take it from here.
COLUMNS = (
    "ready",
    "running",
    "blocked",
    "paused",
    "review",
    "validated",
    "failed",
    "done",
    "cancelled",
)


class Tickets(Base):
    # -- reading --------------------------------------------------------------

    def board(self) -> dict[str, Any]:
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
        goals = self._goal_index()
        host = self.config.runner.session_host

        writes = self.outbox.marks()
        refused = board_module.conflicts(sync.journal(200))
        tickets = [
            board_module.settled(
                board_module.overlay(
                    self._ticket(page, names, projects, host, goals),
                    writes.get(page.id.replace("-", "")),
                    lambda status: names.get(status, "draft"),
                ),
                refused.get(page.id.replace("-", "")),
            )
            for page in pages
        ]
        _causes(tickets)
        _checks(tickets)
        _phases(tickets)
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
        pauses = self._pauses()
        columns = [
            {"key": key, "name": _status(settings, key)}
            for key in keys
            # A board whose `blocked` and `failed` are one column must not
            # be drawn twice under two headings.
            if key == "draft"
            or _status(settings, key)
            not in [_status(settings, other) for other in keys[: keys.index(key)]]
            # And a paused column only where the board has the option: the
            # console offers to pause, and to resume, by the column being there.
            if key != "paused" or pauses
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
            # How many run at once: the column of work in flight reads its fill against it.
            "places": self.config.runner.max_concurrent,
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
        # The goals a new ticket may serve, where the board can point at one.
        if settings.prop("goal") in schema:
            index = self._goal_index()
            if index:
                choices["goal"] = sorted(
                    ({"value": goal["id"], "label": goal["name"]} for goal in index.values()),
                    key=lambda choice: choice["label"].lower(),
                )
        return choices

    def _scored(self) -> bool:
        """Whether this board has a priority column to write a score in."""
        try:
            schema = self.runner.client.schema(self.runner.database)
        except store.StoreError:
            return False
        return self.config.notion.prop("priority") in schema

    def _hold(self, tickets: list[dict[str, Any]]) -> None:
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

    def _ticket(
        self,
        page: store.Page,
        names: dict[str, str],
        projects: dict[str, Any],
        host: str,
        goals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One page of the tickets database, as a card reads it."""
        settings = self.config.notion
        status = str(store.read(page, settings.prop("status")) or "")
        relation = store.read(page, settings.prop("project")) or []
        project = projects.get(relation[0]) if relation else None
        # The goal it serves, read as the runner reads it: the first of the
        # relation. One the index does not know — unreadable, or another
        # database's page — is no goal, and the window says nothing of it.
        pointed = goals_module.pointed(page, settings.prop("goal"))
        goal = (goals or {}).get(pointed) if pointed else None
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
            "goal": (goal or {}).get("name", ""),
            "goal_id": (goal or {}).get("id", ""),
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

    def ticket(self, page_id: str) -> dict[str, Any]:
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
            self._ticket(
                page,
                names,
                self.projects(),
                self.config.runner.session_host,
                self._goal_index(),
            ),
            self.outbox.marks().get(page_id.replace("-", "")),
            lambda status: names.get(status, "draft"),
        )
        _causes([card])
        _checks([card])
        _phases([card])
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
        goal: str = "",
    ) -> dict[str, Any]:
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
        # The goal it serves, only when one is chosen: most tickets serve none.
        if goal.strip():
            values[settings.prop("goal")] = [goal.strip()]
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

    def set_on(self, page_id: str, prompt: str) -> dict[str, Any]:
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

    def transitions(self, page_id: str) -> dict[str, Any]:
        """The executions of one ticket's « On » prompt, newest first."""
        return {"transitions": transitions_module.history(page_id)}

    def set_status(self, page_id: str, key: str, seen: str | None = None) -> dict[str, Any]:
        """Move a ticket: queued now, in Notion as soon as Notion takes it.

        `seen` is the status the card showed when it was moved. A page that says
        anything else by the time the write goes out was moved in Notion
        meanwhile, and is left as it is — see `board.send`. A caller that does
        not say is taken to mean the status the console last read.
        """
        if key not in _keys(self.config.notion):
            raise ValueError(f"unknown column “{key}”")
        settings = self.config.notion
        # A ticket in progress has a session: moving it to paused or cancelled
        # ends that session first, and the worktree is kept or removed with it.
        # Writing the status alone would leave the session going on.
        if key in ("paused", "cancelled") and (
            seen if seen is not None else self._status_of(page_id)
        ) == settings.state("running"):
            return self._stop(page_id, "pause" if key == "paused" else "abandon")
        return self._move(page_id, key, seen)

    def _move(self, page_id: str, key: str, seen: str | None) -> dict[str, Any]:
        """The write of `set_status`, queued: once the board is known to take it."""
        settings = self.config.notion
        if key == "paused" and not self._pauses():
            raise ValueError(
                f"this board has no “{settings.state('paused')}” option to pause a ticket into"
            )
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

    def _stop(self, page_id: str, action: str) -> dict[str, Any]:
        """A ticket in progress, paused or abandoned — whatever state its session is in.

        The run that holds the session is asked through a file (see stopping.py)
        and answers once the session and what it started are gone; only then is
        the worktree touched. A session that was dead already, or a run that is
        not going, answers nothing: nobody is waited for, and the worktree is
        dealt with all the same — which is why this is not left to the run.
        """
        settings = self.config.notion
        key = "paused" if action == "pause" else "cancelled"
        if key == "paused" and not self._pauses():
            raise ValueError(
                f"this board has no “{settings.state('paused')}” option to pause a ticket into"
            )
        if key == "cancelled" and not self._cancels():
            raise ValueError(
                f"this board has no “{settings.state('cancelled')}” option to cancel a ticket into"
            )
        page = self.runner.client.page(page_id)
        status = str(store.read(page, settings.prop("status")) or "")
        if status != settings.state("running"):
            raise ValueError(f"only a ticket in progress can be stopped, not one in “{status}”")
        ticket_id = page_id.replace("-", "")
        stopping.request(ticket_id, action)
        try:
            if stopping.held(ticket_id):
                stopping.wait(ticket_id, STOP_WAIT_SECONDS)
        finally:
            stopping.clear(ticket_id)
        for path in _worktrees(short_id(page_id)):
            if action == "pause":
                git.save(path, "ponos: sauvegarde avant la mise en pause")
            else:
                _remove(path)
        state.release(page_id)
        said = self.runner.voice
        try:
            self.runner.client.comment(
                page_id, said.say("ticket-paused" if action == "pause" else "ticket-abandoned")
            )
            self.runner.forget_comments(page_id)
        except store.StoreError as error:
            # A line of courtesy: the move below is the answer, and does not wait for it.
            logger.warning("%s: the line was not written: %s", page_id, error)
        return self._move(page_id, key, status)

    def _status_of(self, page_id: str) -> str:
        """The status the console last read a ticket in, or "" when it holds none."""
        held = self.reader.get(page_id)
        return str(store.read(held, self.config.notion.prop("status")) or "") if held else ""

    def _send(self, write: board_module.Write) -> store.Page:
        """One attempt at one queued move, and the page it left, held."""
        page = board_module.send(
            self.runner.client, self.runner.database, self.config.notion.prop("status"), write
        )
        self.reader.hold(page)
        return page

    # -- what the board offers ------------------------------------------------

    def _cancels(self) -> bool:
        """Whether this board has a cancelled column of its own — see `cancelled_column`."""
        try:
            return self.runner.cancelled_column()
        except store.StoreError:
            return False

    def _pauses(self) -> bool:
        """Whether this board has a paused column of its own — see `paused_column`."""
        try:
            return self.runner.paused_column()
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


def _worktrees(short: str) -> list[Path]:
    """The directories the runner made for a ticket: its worktree, or its scratch one.

    Found by the ticket's short identifier, which ends their names, rather than
    by recomputing the project's part of it: a ticket worked in another project
    than its own (see `kinds.worked_in`) is named after that one.
    """
    return [
        path
        for folder in ("worktrees", "scratch")
        for path in sorted((state_dir() / folder).glob(f"*-{short}"))
        if path.is_dir()
    ]


def _remove(path: Path) -> None:
    """Take a ticket's directory away, worktree registration and residue included."""
    repo = git.repository_of(path)
    if repo is not None:
        git.remove_worktree(repo, path)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        git.discard(path)


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


def _columns(settings: Notion) -> dict[str, str]:
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


def _keys(settings: Notion) -> tuple[str, ...]:
    """The columns this board draws: the drafts, then the runner's.

    A ticket with no status is a draft, so the drafts are always the first
    column, named or not — see `_draft`.
    """
    return ("draft", *COLUMNS)


def _causes(tickets: list[dict[str, Any]]) -> None:
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


def _times(tickets: list[dict[str, Any]]) -> None:
    """How long Ponos has worked on every card, from the journal's runs in one read.

    `None` on a card the journal has no run for — a ticket from before it, or
    one never taken: the console says « — » there rather than a zero.
    """
    spans = journal.spans() if len(tickets) != 1 else journal.spans(str(tickets[0].get("id", "")))
    for ticket in tickets:
        ticket["worktime"] = worktime.measure(
            spans.get(str(ticket.get("id", "")), []), str(ticket.get("column", ""))
        )


def _subtype(page: store.Page, settings: Notion) -> str:
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


def _checks(tickets: list[dict[str, Any]]) -> None:
    """The state of the checks on every card whose pull request is being followed.

    Read from `ponos.db` in one go, never from GitHub: see `ci.py`. A card that
    is not in review, or whose pull request has no check, carries none.
    """
    rows = state.ci_rows()
    for ticket in tickets:
        row = rows.get(str(ticket.get("id", ""))) if ticket.get("column") == "review" else None
        ticket["ci"] = ci.read(row, str(ticket.get("pull_request") or ""))


def _phases(tickets: list[dict[str, Any]]) -> None:
    """What every card in progress is going through, from `ponos.db` in one read.

    Only there: the row of a ticket that has left is the last thing it went
    through, not what it is going through.
    """
    rows = state.phases()
    for ticket in tickets:
        row = rows.get(str(ticket.get("id", ""))) if ticket.get("column") == "running" else None
        ticket["phase"] = {"key": row[0], "detail": row[1], "since": row[2]} if row else None


def _status(settings: Notion, key: str) -> str:
    """What a column writes: the board's word for it, and for the drafts `_draft`'s."""
    return _draft(settings) if key == "draft" else settings.state(key)


def _draft(settings: Notion) -> str:
    """The status a draft is written with: the option the board already had, or none.

    `draft` is an option the board already had — see `Notion.state` — and it
    counts only when named apart from every status the runner moves a ticket
    through: a draft that is also `ready` is a ticket the runner takes, and
    calling its column "Draft" would be lying. Unnamed, a draft is a ticket
    with no status, and a move to the drafts clears it.
    """
    draft = settings.state("draft")
    return draft if draft and draft not in [settings.state(key) for key in COLUMNS] else ""


def _instant(stamp: str) -> float | None:
    """An ISO time as Notion writes it, in seconds — or None for one it did not write."""
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()
