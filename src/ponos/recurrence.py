"""Tickets that come back on their own, from a row in the Schedules database.

`schedules.py` answers *when*: it reads a cadence and works out the moment the
next occurrence falls on. This is what happens when that moment comes — and
what comes of it is an ordinary ticket, in the ready column, with the same
file, the same session and the same pull request as one you wrote by hand. A
schedule only presses the button for you.

A pass of its own, between `deliver` and the queue: before the queue on
purpose, so a ticket born at 09:00 is claimed by the very pass that made it
rather than by the next one. `recur` holds the four rules that make that safe
to run every ten seconds — catching up, overlapping, idempotence, and whose
clock it all reads.
"""

from __future__ import annotations

from datetime import datetime

from . import priority, state, store
from . import schedules as schedules_module
from . import voice as voice_module
from .base import Base


class Recurrence(Base):
    """What a due schedule becomes, and what is written back on it."""

    def schedules(self) -> list[schedules_module.Schedule]:
        """Every row of the Schedules database, or none where there is no such
        database. Read rather than acted on: `list` and `doctor` want it too."""
        database = self.workspace.schedules
        if not database:
            return []
        settings = self.config.notion
        return [schedules_module.read(page, settings) for page in self.client.query(database)]

    def born(self) -> list[dict]:
        """`recur`, with each birth written into the history — none in a dry run.

        Before the queue, so a ticket born at 09:00 is claimed by the very pass
        that made it rather than by the next one. A birth is an entry of its own
        kind: `ponos history` shows it as it shows a merge.

        A Schedules database that no longer answers — taken out of the
        integration, say — costs a line here and nothing else: the queue that
        follows is the runner's own business, not this one's.
        """
        try:
            born = self.recur()
        except store.Unreachable:
            raise
        except store.StoreError as error:
            self.say(f"  ! the schedules could not be read: {voice_module.line(error)}")
            return []
        newborns = [entry for entry in born if entry.get("status") != "dry-run"]
        for entry in newborns:
            state.record(entry)
        return newborns

    def recur(self) -> list[dict]:
        """The schedules whose moment has come, turned into tickets.

        A pass of its own, between `deliver` and the queue — before the queue on
        purpose, so a ticket born at 09:00 is claimed by the very pass that made
        it rather than by the next one. What it produces is an ordinary ticket:
        same ready column, same file, same session, same pull request. The
        schedule only presses the button for you.

        Four rules, and they are the whole of it.

        - **Catching up: one occurrence, and the missed ones are dropped.**
          Machine off for three days, timer stopped, laptop shut: waking up
          gives you one ticket for the occurrence that is due, not twelve. The
          next moment is computed *from now*, never by stacking up what was
          lost. This is anacron, not cron — turning a laptop back on must not
          set off an avalanche of sessions.
        - **Overlapping: skipped, and said out loud.** While the ticket of the
          previous occurrence is neither done nor failed, no new one is made.
          The next moment moves on regardless. Without that, one schedule stuck
          on a question fills the board with twenty identical tickets.
        - **Idempotence: the occurrence is taken before it is acted on.** `Next`
          and `Last` are written first, the ticket second. A crash in between
          loses one occurrence; the other order would create two, which costs a
          session and dirties the board. A second runner on another machine
          reads a `Next` that has already moved, and does nothing.
        - **The timezone is this machine's**, the same reading `scheduled_for`
          gives a date on a ticket.
        """
        if not self.config.runner.schedule:
            return []
        born: list[dict] = []
        now = datetime.now().astimezone()
        for schedule in self.schedules():
            if not schedule.active or schedule.problem:
                # A schedule nobody can read holds nobody up: `doctor` names it,
                # and the others go on being born.
                continue
            upcoming = schedules_module.next_occurrence(
                schedule.cadence, schedule.at, schedule.day, after=now
            )
            if schedule.next is None:
                # A new schedule does not fire the second it is written: writing
                # “Weekly / Monday” on a Tuesday must not produce a ticket now.
                if upcoming:
                    self._mark(schedule, {self.config.notion.prop("next_run"): upcoming})
                    self.say(
                        f"  ⧗ {schedule.name} — first occurrence "
                        f"{upcoming.strftime('%Y-%m-%d %H:%M')}"
                    )
                continue
            if schedule.next > now or upcoming is None:
                # `problem` already caught everything that makes a cadence
                # uncomputable; taking an occurrence without knowing when the
                # next one falls would have this fire on every single pass.
                continue
            if self.dry_run:
                self.say(f"  (dry run) {schedule.name} — due: would create a ticket")
                born.append({"ticket": schedule.name, "status": "dry-run"})
                continue
            # Taken before it is done: see the third rule above.
            self._mark(
                schedule,
                {
                    self.config.notion.prop("next_run"): upcoming,
                    self.config.notion.prop("last_run"): now,
                },
            )
            if self._busy(schedule):
                self.say(f"  · {schedule.name} — its last ticket is still open, no second one made")
                continue
            entry = self._born(schedule)
            if entry:
                born.append(entry)
        return born

    def launch(self, page_id: str) -> dict:
        """One schedule's occurrence, now, whatever its clock says.

        What the console's “Run now” presses. The ticket is the one `recur`
        would have made, but the bookkeeping is not: `Next` stays where it is,
        so the planned occurrence still happens, and only `Last` moves. A paused
        schedule launches too — that is how one is tried before it is turned on —
        and stays paused. The previous ticket still being open is no reason to
        refuse: somebody asked, which a pass cannot say.

        A failure is raised rather than said, since there is somebody to tell.
        """
        wanted = page_id.replace("-", "")
        schedule = next(
            (item for item in self.schedules() if item.page.id.replace("-", "") == wanted), None
        )
        if schedule is None:
            raise LookupError(f"no schedule with id {wanted}")
        if schedule.problem:
            raise ValueError(schedule.problem)
        entry = self._born(schedule, strict=True)
        assert entry is not None
        # After the ticket rather than before, unlike a pass: nobody is racing
        # this one for the occurrence, and a `Last` that moved for a ticket that
        # was never made would be a lie.
        self._mark(schedule, {self.config.notion.prop("last_run"): datetime.now().astimezone()})
        state.record(entry)
        return entry

    def _busy(self, schedule: schedules_module.Schedule) -> bool:
        """Is the previous occurrence still going?

        Anywhere but done, failed or cancelled — so still ready, in progress, in review,
        validated, or blocked on a question nobody has answered — means yes. A
        ticket the integration can no longer read is not one of those: a page
        somebody deleted would otherwise wedge its schedule for good.
        """
        if not schedule.last_ticket:
            return False
        settings = self.config.notion
        try:
            page = self.client.page(schedule.last_ticket)
        except store.StoreError:
            return False
        status = str(store.read(page, settings.prop("status")) or "")
        return status not in (
            settings.state("done"),
            settings.state("failed"),
            settings.state("cancelled"),
        )

    def _born(self, schedule: schedules_module.Schedule, *, strict: bool = False) -> dict | None:
        """One schedule, one ticket, in the ready column.

        The body is a line saying where it came from, then the schedule page's
        own body copied under it — the same road a report travels. Copied rather
        than linked, so the ticket reads on its own and its history shows what
        was actually asked for that day.

        The project, the model, the priority, the type and the sub-type are
        copied too. The type above all: a ticket born with one is never
        classified (see `Preparation._kind`), and a brief long and well written
        enough reads as « Rédaction » to a classifier — a code ticket that then
        writes its answer in the page and goes to done, its pull request opened
        by hand and lost to the board.

        A schedule that fails takes only itself down: the pass says so and moves
        on to the next one. `strict`, for a launch somebody asked for: the
        failure is raised to them instead.
        """
        settings = self.config.notion
        moment = datetime.now().astimezone()
        stamp = moment.strftime("%Y-%m-%d %H:%M" if schedule.cadence == "Hourly" else "%Y-%m-%d")
        title = f"{schedule.name} — {stamp}"
        values: dict[str, object] = {settings.prop("status"): settings.state("ready")}
        for key, value in (
            ("project", schedule.project),
            ("model", schedule.model),
            ("type", schedule.kind),
            ("subtype", schedule.subtype),
        ):
            if value:
                values[settings.prop(key)] = value
        # Always written: a ticket a schedule makes says its score on the board,
        # the schedule's or the middle one.
        values[settings.prop("priority")] = self.priority_cell(
            priority.DEFAULT if schedule.priority is None else schedule.priority
        )
        # The brief is read before anything is written: the page it comes from is
        # the likeliest thing to be unreadable, and a ticket that is all title
        # would run on nothing at all.
        try:
            brief = self.client.blocks_text(schedule.page.id, live=False)
            page_id = self.client.create_row(self.database, title, values)
        except store.StoreError as error:
            if strict:
                raise
            self.say(
                f"  ! {schedule.name} — the ticket could not be created: {voice_module.line(error)}"
            )
            return None
        # Linked first, so that a body Notion refuses still leaves the schedule
        # knowing what it produced — otherwise the next occurrence makes a twin.
        self._mark(schedule, {settings.prop("last_ticket"): page_id})
        try:
            self.client.append_markdown(
                page_id,
                self.voice.say(
                    "born-of-schedule", name=schedule.name, stamp=stamp, url=schedule.page.url
                )
                + "\n"
                + (f"\n{brief}\n" if brief.strip() else ""),
            )
        except store.StoreError as error:
            self.say(f"  ! {title} — created, but its body was refused: {voice_module.line(error)}")
        self.say(f"  ✳ {title} — created by a schedule, ready")
        return {
            "ticket": title,
            "id": page_id.replace("-", ""),
            "status": "scheduled",
            "from": schedule.name,
        }

    def _mark(self, schedule: schedules_module.Schedule, values: dict[str, object]) -> None:
        """Write back onto a schedule. Never a reason to fail a pass.

        Dates go over as ISO 8601 rather than as `str(datetime)`, which spells
        the separator as a space and is not what Notion accepts.
        """
        if self.dry_run or not self.workspace.schedules:
            return
        written = {
            name: value.isoformat() if isinstance(value, datetime) else value
            for name, value in values.items()
        }
        try:
            self.client.update(self.workspace.schedules, schedule.page.id, written)
        except store.StoreError as error:
            self.say(f"  ! {schedule.name} — Notion refused the write: {voice_module.line(error)}")
