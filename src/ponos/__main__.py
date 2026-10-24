"""The command line interface.

`run` is what the systemd timer calls; everything else exists so you can find
out what it did without reading a systemd journal.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import (
    channels,
    conversation,
    credits,
    db,
    environment,
    git,
    health,
    journal,
    leftovers,
    legacy,
    log,
    notion,
    priority,
    provision,
    session,
    state,
    store,
    subtypes,
    systemd,
    voice,
)
from . import config as config_module
from . import schedules as schedules_module
from . import update as update_module
from .runner import Runner
from .ticket import Ticket, short_id

BOLD, DIM, GREEN, RED, YELLOW, RESET = "", "", "", "", "", ""
if sys.stdout.isatty():
    BOLD, DIM = "\033[1m", "\033[2m"
    GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# The command is `ponos`, the product Ponos: argparse and `--version` say the
# first, sentences the second.
PRODUCT = "ponos"
NAME = "Ponos"
TAGLINE = "Turns ready Notion tickets into Claude Code sessions."


def ok(message: str) -> None:
    print(f"  {GREEN}✓{RESET} {message}")


def bad(message: str) -> None:
    print(f"  {RED}✗{RESET} {message}")


def warn(message: str) -> None:
    print(f"  {YELLOW}!{RESET} {message}")


def title(message: str) -> None:
    print(f"{BOLD}{message}{RESET}")


def _names(reference: str, filename: str) -> bool:
    """Does this log belong to that ticket, however the ID was pasted?

    A full ID, a dashed one, a URL, or just the short form all have to work —
    log files are named by the ticket's *last* eight characters, which is not
    what someone copying an ID from Notion has in hand.
    """
    probe = reference.strip().rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1].replace("-", "")
    forms = {probe, probe[-8:]} if len(probe) >= 8 else {probe}
    return any(form and form in filename for form in forms)


def _colour(status: str) -> str:
    """Blocked is not a failure: it is a ticket waiting for you."""
    return {"done": GREEN, "failed": RED, "blocked": YELLOW}.get(status, DIM)


def load_config() -> config_module.Config:
    try:
        configuration = config_module.load()
        configuration.require_usable()
        return configuration
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        raise SystemExit(2) from error


# -- commands ----------------------------------------------------------------


def command_run(args: argparse.Namespace) -> int:
    if getattr(args, "every", None) is not None:
        return run_every(args)
    if not config_module.readable() and update_module.app_dir().is_symlink():
        return _environment_first()
    configuration = load_config()
    runner = Runner(configuration, dry_run=args.dry_run, announce_idle=sys.stdout.isatty())
    try:
        with state.lock():
            results = runner.tick(limit=args.limit, reference=args.ticket or "")
    except state.Busy as error:
        print(f"{DIM}{error}{RESET}")
        return 0
    except store.Unreachable as error:
        # A network that is down is not a failed run: the timer would otherwise
        # report the service as failing every few seconds until it came back,
        # and the next pass is the one that finds it back.
        print(f"{DIM}offline — nothing is run until the network is back ({error}){RESET}")
        return 0
    except store.StoreError as error:
        print(f"{RED}the board:{RESET} {error}", file=sys.stderr)
        return 1
    failures = sum(1 for result in results if result.get("status") == "failed")
    # The timer should only see a failure if the whole run failed: one ticket
    # out of three going wrong is not a service outage.
    return 1 if results and failures == len(results) else 0


def _environment_first() -> int:
    """A pass on a Python that cannot read the configuration: the environment, and only that.

    The machine's Python, running a version that an older one installed before
    versions had an environment (see environment.py): it has no pydantic, so
    no configuration and no ticket — but it can make the `.venv` that has it,
    under the run lock as a pass would, and the launcher starts the next pass
    in it.
    """
    try:
        with state.lock():
            problem = update_module.heal_environment()
    except state.Busy as error:
        print(f"{DIM}{error}{RESET}")
        return 0
    if problem:
        print(f"{RED}error:{RESET} {problem}", file=sys.stderr)
        return 1
    print(f"{DIM}this version's environment is made — the next run starts in it{RESET}")
    return 0


# How often a loop waiting for its next run looks at the configuration. A file
# that moved is somebody who has just set the board up, or changed the interval:
# the next run is started then, rather than up to an interval later.
LOOP_GLANCE = 5.0


def run_every(args: argparse.Namespace, *, passes: int = 0) -> int:
    """What the systemd timer does, for a machine that has no systemd — a container.

    Each run is `ponos run` in a process of its own, exactly what the timer
    starts: it takes the run lock like any other, so a run already going — the
    console's `run`, a second loop — turns it away as busy rather than doubling
    it; and it imports the code on disk, so a run never outlives the version it
    started on. The interval is read from the configuration before every wait
    unless `--every` named one, so changing it in the console needs no restart.

    `passes` stops after that many runs; zero is forever. For the tests.
    """
    command = [sys.executable, "-m", PRODUCT, "run"]
    for flag, value in (("--ticket", args.ticket), ("--limit", args.limit)):
        if value:
            command += [flag, str(value)]
    if args.dry_run:
        command.append("--dry-run")
    # The sources this process was started from, so `-m ponos` finds them
    # whatever launched it — the launcher, the image, a checkout.
    source = str(Path(__file__).resolve().parents[1])
    inherited = os.environ.get("PYTHONPATH", "")
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(part for part in (source, inherited) if part),
    }
    done = 0
    waiting = False
    while True:
        started = time.monotonic()
        if _usable():
            waiting = False
            subprocess.run(command, env=environment)
        elif not waiting:
            # A container's first minutes: the console is up, nobody has given
            # it a board yet. Said once, rather than as an error every minute.
            print(
                f"{DIM}no board configured yet — the first run starts once there is one{RESET}",
                flush=True,
            )
            waiting = True
        # Read after the run, which may write the file itself.
        seen = _config_stamp()
        done += 1
        if passes and done >= passes:
            return 0
        interval = args.every or _interval()
        while time.monotonic() - started < interval:
            time.sleep(min(LOOP_GLANCE, max(0.0, interval - (time.monotonic() - started))))
            if _config_stamp() != seen:
                break


def _usable() -> bool:
    try:
        config_module.load().require_usable()
    except config_module.ConfigError:
        return False
    return True


def _interval() -> int:
    try:
        return config_module.load().runner.interval_seconds
    except config_module.ConfigError:
        return config_module.Runner().interval_seconds


def _config_stamp() -> float:
    try:
        return config_module.config_path().stat().st_mtime
    except OSError:
        return 0.0


def command_list(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    tickets, waiting = runner.queue()
    # The validated column keeps a calendar of its own: what you have accepted
    # and dated is waiting to go out, exactly as a dated ready ticket is waiting
    # to run. One list, or the half of it that is shown lies about the other.
    rows = [(ticket, moment, "") for ticket, moment in waiting]
    rows += [(ticket, moment, " · validated") for ticket, moment in runner.scheduled()]
    rows.sort(key=lambda row: row[1])
    # And what is not written yet: a schedule is as much a thing about to happen
    # as a dated ticket is. Showing one without the other would be half a
    # calendar, and the half that surprises you is always the other one.
    births = (
        sorted(
            (
                (schedule, moment)
                for schedule in runner.schedules()
                if schedule.active and (moment := schedule.next) and not schedule.problem
            ),
            key=lambda born: born[1],
        )
        if configuration.runner.schedule
        else []
    )
    if not tickets and not rows and not births:
        print("No ticket ready.")
        return 0
    if tickets:
        title(f"{len(tickets)} ticket(s) to handle, in the order they will run")
    for position, ticket in enumerate(tickets, 1):
        relation = store.read(ticket.page, configuration.notion.prop("project")) or []
        project, kind = "?", ""
        if relation:
            try:
                resolved = runner.resolver.resolve(runner.client, relation[0])
                project = resolved.name
                kind = "code" if resolved.is_code else "document"
            except (LookupError, store.StoreError):
                project = f"{YELLOW}project not found{RESET}"
        score = store.read(ticket.page, configuration.notion.prop("priority"))
        badges = [
            f"priority {priority.score(score)}" if score not in (None, "") else "",
            str(store.read(ticket.page, configuration.notion.prop("model")) or ""),
        ]
        tail = " · ".join([part for part in [project, kind, *badges] if part])
        print(
            f"  {position}. {ticket.title}\n     {DIM}{tail}{RESET}\n     {DIM}{ticket.url}{RESET}"
        )

    now = datetime.now().astimezone()
    if rows:
        title(f"\n{len(rows)} ticket(s) waiting for their date")
        for ticket, moment, note in rows:
            print(f"  {ticket.title}\n     {DIM}{_when(moment, now)}{note}{RESET}")

    if births:
        title(f"\n{len(births)} ticket(s) not written yet")
        for schedule, moment in births:
            cadence = " · ".join(
                part for part in (schedule.cadence, schedule.day, schedule.at) if part
            )
            print(f"  {schedule.name}\n     {DIM}{_when(moment, now)} · {cadence}{RESET}")
    return 0


def _when(moment: datetime, now: datetime) -> str:
    """“2026-09-14 09:00 — in 6 days”, the way `list` says a date."""
    delay = moment - now
    hours = delay.total_seconds() / 3600
    if hours < 0:
        return f"{moment.strftime('%Y-%m-%d %H:%M')} — overdue"
    near = f"in {hours:.0f} h" if hours < 48 else f"in {delay.days} days"
    return f"{moment.strftime('%Y-%m-%d %H:%M')} — {near}"


def command_subtypes(args: argparse.Namespace) -> int:
    """The sub-types of the code tickets, and — with --backfill — the ones a prefix says.

    See `Board.backfill_subtypes`: the title's prefix alone, never a session.
    """
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    column = runner.subtype_column()
    if not column:
        bad(f"no “{configuration.notion.prop('subtype')}” column on the board — ponos init adds it")
        return 1
    if args.backfill:
        try:
            filled = runner.backfill_subtypes(write=not args.dry_run, closed=args.all)
        except store.StoreError as error:
            bad(f"the board refused: {error}")
            return 1
        verb = "would be filled" if args.dry_run else "filled"
        title(f"{len(filled)} code ticket(s) {verb} from their prefix")
        for page, key in filled:
            print(f"  {subtypes.BY_KEY[key].icon} {subtypes.option(key):<13} {page.title}")
        return 0
    counts: dict[str, int] = {}
    for page in runner.client.query(runner.database):
        if runner.kind(Ticket(page)) == "code":
            key = subtypes.of(store.read(page, column))
            counts[key] = counts.get(key, 0) + 1
    title("Code tickets, by sub-type")
    for subtype in subtypes.SUBTYPES:
        print(f"  {subtype.icon} {subtype.option:<13} {counts.get(subtype.key, 0)}")
    print(f"  {DIM}  {'(none)':<13} {counts.get('', 0)}{RESET}")
    if counts.get(""):
        print(
            f"  {DIM}ponos subtypes --backfill fills the open ones whose title has a prefix; "
            f"--all the done ones too, which dates their closing today in the statistics{RESET}"
        )
    return 0


def command_schedules(args: argparse.Namespace) -> int:
    """What repeats, when it next happens, and how the last one went.

    `--run` is what makes the thing tryable: a schedule you have just written
    should not need you to wait until Monday to find out what it produces.
    """
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    try:
        rows = runner.schedules()
    except store.StoreError as error:
        print(f"{RED}the board:{RESET} {error}", file=sys.stderr)
        return 1

    if not runner.workspace.schedules:
        print("Nothing repeats here.")
        print(
            f"  {DIM}no “{configuration.notion.page('schedules')}” page in the workspace"
            f" — ponos init <page-url> builds it{RESET}"
        )
        return 0
    if args.run:
        return _run_schedule(runner, rows, args.run, force=args.force)
    if not rows:
        print("Nothing repeats here yet — the schedules database is empty.")
        return 0

    now = datetime.now().astimezone()
    title(f"{len(rows)} schedule(s)")
    for schedule in rows:
        mark = f"{GREEN}✓{RESET}" if schedule.active else f"{DIM}·{RESET}"
        cadence = schedule.cadence or f"{YELLOW}no cadence{RESET}"
        when = " ".join(part for part in (schedule.day, schedule.at) if part)
        print(f"  {mark} {schedule.name}  {DIM}{cadence}{(' · ' + when) if when else ''}{RESET}")
        if schedule.problem:
            print(f"     {YELLOW}{schedule.problem}{RESET}")
            continue
        if not schedule.active:
            print(f"     {DIM}unticked — nothing is born{RESET}")
            continue
        nxt = _when(schedule.next, now) if schedule.next else "not computed yet"
        last = schedule.last.strftime("%Y-%m-%d %H:%M") if schedule.last else "never"
        print(f"     {DIM}next {nxt} · last {last}{RESET}")
        if schedule.last_ticket:
            state_of = "still open" if runner._busy(schedule) else "finished"  # noqa: SLF001
            print(f"     {DIM}last occurrence: {state_of}{RESET}")
    if not configuration.runner.schedule:
        warn("runner.schedule = false — none of this runs")
    return 0


def _run_schedule(
    runner: Runner, rows: list[schedules_module.Schedule], reference: str, *, force: bool
) -> int:
    """Make one schedule's ticket now, without waiting for its hour."""
    wanted = reference.strip().lower()
    matches = [row for row in rows if row.name.lower() == wanted] or [
        row for row in rows if wanted in row.name.lower()
    ]
    if not matches:
        bad(f"no schedule named “{reference}”")
        print(f"    {DIM}{', '.join(row.name for row in rows) or 'the database is empty'}{RESET}")
        return 1
    if len(matches) > 1:
        warn(f"{len(matches)} schedules match “{reference}” — name one of them:")
        for row in matches:
            print(f"    {row.name}")
        return 1

    schedule = matches[0]
    if schedule.problem:
        bad(f"{schedule.name} — {schedule.problem}")
        return 1
    # The overlap rule holds here too: triggering by hand is still an
    # occurrence, and two of them open at once is the thing it exists to stop.
    # `--force` is how you say you meant it.
    if not force and runner._busy(schedule):  # noqa: SLF001
        warn(f"{schedule.name} — its last ticket is still open")
        print(f"    {DIM}ponos schedules --run “{schedule.name}” --force{RESET}")
        return 1
    entry = runner._born(schedule)  # noqa: SLF001
    if not entry:
        return 1
    # `Next` is left where it is: triggering by hand borrows an occurrence, it
    # does not move the rhythm. The one it was already due is skipped by the
    # overlap rule if this ticket is still open when it comes round.
    runner._mark(  # noqa: SLF001
        schedule,
        {runner.config.notion.prop("last_run"): datetime.now().astimezone()},
    )
    state.record(entry)
    ok(f"{entry['ticket']} — created, waiting in “{runner.config.notion.state('ready')}”")
    return 0


def command_projects(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    seen: dict[str, None] = {}
    for ticket in runner.client.query(runner.database):
        for page_id in store.read(ticket, configuration.notion.prop("project")) or []:
            seen.setdefault(page_id, None)
    if not seen:
        print("No project referenced by any ticket.")
        return 0
    title(f"Referenced projects ({len(seen)})")
    failed = 0
    for page_id in seen:
        try:
            project = runner.resolver.resolve(runner.client, page_id)
            where = project.path if project.is_code else f"{DIM}document — no repository{RESET}"
            if project.is_stale:
                # Resolved, and its tickets run — on a fallback. Neither a
                # tick nor a cross: the repository is right, the page is not.
                warn(f"{project.name} → {where}\n    {project.note}")
            else:
                ok(f"{project.name} → {where}")
            if project.path and (why := health.base_without_ci(project.path, configuration.github)):
                warn(f"{project.name}: {why}")
        except (LookupError, store.StoreError) as error:
            failed += 1
            bad(str(error).replace("\n", "\n    "))
    return 1 if failed else 0


def command_sync(args: argparse.Namespace) -> int:
    """Reconcile the Notion board and the Markdown one, and say what moved.

    A pass already does this on its own when `storage.mode = "both"`. This is
    for the two moments a pass is no help: the first reconciliation, where you
    want to watch what a full board does before it does it to both copies, and
    after an editing session in the files, where waiting for the timer is a
    silly way to find out whether the frontmatter was readable.
    """
    from . import sync as sync_module

    configuration = load_config()
    if args.journal:
        entries = sync_module.journal(args.number)
        if not entries:
            print("Nothing has been synchronised yet.")
            return 0
        title(f"The last {len(entries)} entries")
        for entry in entries:
            mark = {
                "conflict": YELLOW,
                "deleted-in-notion": YELLOW,
                "deleted-in-markdown": YELLOW,
                "drift": YELLOW,
                "write-failed": YELLOW,
            }
            colour = mark.get(entry.get("what", ""), DIM)
            said = " — " + entry["detail"] if entry.get("detail") else ""
            print(
                f"  {entry.get('at', '')[:16]}  {colour}{entry.get('what', '')}{RESET}  "
                f"{entry.get('title') or entry.get('page', '')}{DIM}{said}{RESET}"
            )
        return 0

    if configuration.storage.mode != "both":
        bad(f'storage.mode is "{configuration.storage.mode}" — there is only one board to read')
        print(f'  {DIM}set storage.mode = "both" to keep Notion and Markdown in step{RESET}')
        return 2

    from .sync import Mirror

    backend = store.open(configuration)
    assert isinstance(backend, Mirror)  # what `storage.mode = "both"` opens
    title("Reconciling")
    report = backend.synchronise(configuration.notion)
    for problem in report.problems:
        bad(problem)
    for moved in report.carried:
        ok(f"{moved.what}  {moved.title or moved.page}")
    for conflict in report.conflicts:
        warn(f"{conflict.title or conflict.page} — {conflict.detail}")
    for deletion in report.deletions:
        warn(f"{deletion.title or deletion.page} — {deletion.detail}")
    if not report:
        print(f"  {DIM}nothing to carry across — the two boards agree{RESET}")
    print(
        f"\n{len(report.carried)} carried, {len(report.conflicts)} conflict(s), "
        f"{len(report.deletions)} deletion(s) — journal: ponos sync --journal"
    )
    return 1 if report.problems else 0


def command_history(args: argparse.Namespace) -> int:
    entries = state.history(args.number)
    if not entries:
        print("No ticket handled yet.")
        return 0
    for entry in entries:
        status = entry.get("status", "?")
        colour = _colour(status)
        seconds = entry.get("seconds")
        timing = (
            f" {DIM}({seconds / 60:.0f} min){RESET}" if isinstance(seconds, (int, float)) else ""
        )
        cost = entry.get("cost_usd")
        price = f" {DIM}(${float(cost):.2f}){RESET}" if isinstance(cost, (int, float)) else ""
        line = f"  {colour}{status:<7}{RESET} {entry.get('at', '')}  {entry.get('ticket', '')}{timing}{price}"
        print(line)
        detail = entry.get("pull_request") or entry.get("reason") or ""
        if detail:
            print(f"          {DIM}{detail}{RESET}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    try:
        configuration = config_module.load()
    except config_module.ConfigError as error:
        bad(str(error))
        return 2

    title("Services")
    if shutil.which("systemctl"):
        _timer_line(systemd.read())
        # The console runs by default, so its absence is worth a line: nothing
        # about a ticket goes wrong when it is down, you simply have no board.
        console = subprocess.run(
            ["systemctl", "--user", "is-active", "ponos-web.service"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        (ok if console == "active" else warn)(f"ponos-web.service: {console or 'not installed'}")
        if console == "active":
            print(f"    {DIM}http://{configuration.web.host}:{configuration.web.port}{RESET}")
        else:
            print(f"    {DIM}ponos enable   to start it{RESET}")
    else:
        warn("no systemd — the runner only runs on demand")

    held = state.running()
    if held:
        warn(f"a run is in progress ({held})")
    else:
        ok("no run in progress")

    # A runner that is on, has tickets and does nothing looks broken. It is not:
    # the subscription's window is spent — or down to the share you asked to
    # keep — and the wait is the point. Both are said, because they stop
    # different things: the first stops everything, the second only what would
    # start a session.
    until = credits.held()
    if until:
        warn(f"out of credit — nothing is run until {credits.when(until)}")
    reserved = credits.held(what="reserve")
    reading = credits.used()
    if reserved:
        warn(
            f"{configuration.runner.credit_reserve_percent}% of the subscription is "
            f"held in reserve — nothing new is started until {credits.when(reserved)}"
        )
    elif reading is None:
        warn("how much of the subscription is spent could not be read — the reserve is idle")
    else:
        ok(
            f"{reading[0]:.0f}% of the subscription spent, "
            f"{configuration.runner.credit_reserve_percent}% held in reserve"
        )

    limit = configuration.budget.daily_usd
    if limit > 0:
        spent = state.spent_today()
        (warn if spent >= limit else ok)(
            f"{spent:.2f} $ spent today, daily limit {limit:.2f} $"
            + (" — nothing new is started until midnight" if spent >= limit else "")
        )
    if configuration.budget.per_ticket_usd > 0:
        ok(f"per-ticket limit {configuration.budget.per_ticket_usd:.2f} $")
    if configuration.runner.on:
        cap = configuration.budget.on_usd
        ok(
            f"« On » prompts: {f'{cap:.2f} $ each' if cap > 0 else 'no spending limit'}, "
            f"{configuration.runner.on_max_depth} generation(s) of chained tickets"
        )

    rules = configuration.permissions
    ok(f"permissions: {len(rules.allowed)} done alone, {len(rules.ask)} always asked")

    title("Board")
    try:
        configuration.require_usable()
        runner = Runner(configuration, quiet=True)
        counts: dict[str, int] = {}
        for page in runner.client.query(runner.database):
            name = str(store.read(page, configuration.notion.prop("status")) or "—")
            counts[name] = counts.get(name, 0) + 1
        if not counts:
            print(f"  {DIM}no ticket{RESET}")
        ready_state = configuration.notion.state("ready")
        for name, number in sorted(counts.items(), key=lambda item: -item[1]):
            highlight = GREEN if name == ready_state else DIM
            print(f"  {highlight}{number:>3}{RESET}  {name}")
    except (config_module.ConfigError, store.StoreError) as error:
        bad(f"Notion unreachable: {str(error).splitlines()[0]}")

    title("Recent tickets")
    entries = state.history(5)
    if not entries:
        print(f"  {DIM}none{RESET}")
    for entry in entries:
        status = entry.get("status", "?")
        seconds = entry.get("seconds")
        timing = (
            f" {DIM}({seconds / 60:.0f} min){RESET}" if isinstance(seconds, (int, float)) else ""
        )
        print(f"  {_colour(status)}{status:<7}{RESET} {entry.get('ticket', '')}{timing}")
        detail = entry.get("pull_request") or entry.get("reason") or ""
        if detail:
            print(f"          {DIM}{str(detail)[:90]}{RESET}")

    _, spend = state.totals()
    if spend:
        print(f"\n  {DIM}reported spend so far: ${spend:.2f}{RESET}")
    return 0


def _journal_runs(ticket: str = "") -> list[dict[str, Any]]:
    """A ticket's runs from the local journal, newest first — none if it cannot be read."""
    try:
        return journal.runs(ticket)
    except (db.DatabaseError, sqlite3.Error) as error:
        print(f"{DIM}(the run journal cannot be read: {error}){RESET}", file=sys.stderr)
        return []


def _print_runs(runs: list[dict[str, Any]]) -> int:
    """`ponos logs --runs`: one line per run, and the log that holds all of it."""
    if not runs:
        print("No run in the journal yet.")
        return 0
    for run in runs:
        status = run["status"] or ("running" if not run["ended_at"] else "?")
        cost = f" · ${run['cost_usd']:.2f}" if run["cost_usd"] else ""
        print(
            f"  {_colour(status)}{status:<9}{RESET} {run['started_at'][:16].replace('T', ' ')}"
            f"  {short_id(run['ticket'])}  {run['title']}  {DIM}{run['steps']} steps{cost}{RESET}"
        )
        detail = run["reason"]
        if detail:
            print(f"            {DIM}{str(detail)[:90]}{RESET}")
        if run["log"]:
            print(f"            {DIM}{state.logs_dir() / run['log']}{RESET}")
    return 0


def _print_service(follow: bool) -> int:
    """`ponos logs --service`: the end of ponos.log, and what is written next with -f."""
    target = log.path()
    if not target.exists():
        print("No service log yet.")
        return 0
    print(f"{DIM}{target}{RESET}", file=sys.stderr)
    for line in log.tail(200, target):
        print(line)
    if not follow:
        return 0
    handle = target.open(encoding="utf-8", errors="replace")
    handle.seek(0, os.SEEK_END)
    try:
        while True:
            line = handle.readline()
            if line:
                print(line, end="", flush=True)
                continue
            # Turned over by whoever wrote past a megabyte: the new file, from its start.
            try:
                moved = os.stat(target).st_ino != os.fstat(handle.fileno()).st_ino
            except OSError:
                moved = False
            if moved:
                handle.close()
                handle = target.open(encoding="utf-8", errors="replace")
                continue
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        handle.close()


def command_logs(args: argparse.Namespace) -> int:
    if args.service:
        return _print_service(args.follow)
    if args.runs:
        return _print_runs(_journal_runs(args.ticket or ""))
    logs = sorted(state.logs_dir().glob("*.jsonl"))
    if not logs:
        print("No log yet.")
        return 0
    target = logs[-1]
    if args.ticket:
        # The journal knows a ticket's runs whatever their log is called — a
        # session started over writes to a second one. The file names are what
        # is left for runs older than the journal.
        known = [
            state.logs_dir() / run["log"]
            for run in _journal_runs(args.ticket)
            if run["log"] and (state.logs_dir() / run["log"]).exists()
        ]
        matches = known[:1] or [path for path in logs if _names(args.ticket, path.name)][-1:]
        if not matches:
            print(f"No log for {args.ticket}", file=sys.stderr)
            return 1
        target = matches[-1]
    print(f"{DIM}{target}{RESET}", file=sys.stderr)
    if args.raw:
        print(target.read_text(encoding="utf-8", errors="replace"))
        return 0
    handle = target.open(encoding="utf-8", errors="replace")
    try:
        while True:
            line = handle.readline()
            if not line:
                if not args.follow:
                    return 0
                time.sleep(0.5)
                continue
            rendered = _render(line)
            if rendered:
                print(rendered, flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        handle.close()


def _render(line: str) -> str:
    """One line of the stream-json feed, reduced to what reads."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return ""
    kind = event.get("type")
    if kind == "assistant":
        pieces = []
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                pieces.append(block["text"].strip())
            elif block.get("type") == "tool_use":
                name = block.get("name", "?")
                target = block.get("input", {})
                hint = (
                    target.get("file_path") or target.get("command") or target.get("pattern") or ""
                )
                pieces.append(f"{DIM}· {name} {str(hint)[:100]}{RESET}")
        return "\n".join(pieces)
    if kind == "result":
        cost = event.get("total_cost_usd") or 0
        return f"{BOLD}— end —{RESET} {event.get('num_turns', 0)} turns · ${cost:.3f}"
    return ""


def command_init(args: argparse.Namespace) -> int:
    """Build the whole Notion side from one page link.

    The only thing asked of the user beforehand is the one thing no API can do:
    share a page with the integration. An integration cannot grant itself
    access, so that click is the floor — everything past it is done here.
    """
    try:
        configuration = config_module.load()
    except config_module.ConfigError as error:
        bad(str(error))
        return 2

    token = (args.token or configuration.notion.token).strip()
    if not token or token == config_module.PLACEHOLDER:
        bad("no Notion token yet")
        print(
            f"    {DIM}create an internal integration at "
            f"https://www.notion.so/my-integrations{RESET}\n"
            f"    {DIM}then: ponos init <page-url> --token ntn_…{RESET}"
        )
        return 2

    page = config_module.identifier(args.page)
    if not config_module.is_identifier(page):
        bad(f"“{args.page}” does not contain a Notion page ID")
        print(f"    {DIM}copy the page's link: ··· → Copy link{RESET}")
        return 2

    client = notion.Client(token)

    title("Page")
    try:
        target = client.page(page)
    except store.StoreError as error:
        bad(f"unreachable: {str(error).splitlines()[0]}")
        warn("open the page in Notion → ··· → Connections → add your integration")
        return 1
    ok(f"“{target.title or page}”")

    title("Workspace")
    try:
        report = provision.provision(client, configuration.notion, page, demo=not args.no_demo)
    except store.StoreError as error:
        # The API's validation errors say what is wrong on the lines after the
        # first one; cutting them off leaves “body failed validation. Fix one:”.
        first, *rest = str(error).splitlines()
        bad(first)
        for line in rest:
            print(f"    {DIM}{line}{RESET}")
        warn("what was built is kept: run the same command again once it is fixed")
        return 1
    for verb, what in report.steps:
        if verb == "created":
            ok(what)
        elif verb == "kept":
            _kept(what)
        else:
            warn(what)

    title("Configuration")
    if args.token:
        # Beside the file rather than in it: config.toml holds no secret.
        secrets = config_module.secrets_path(configuration.path)
        config_module.write_secrets(secrets, {config_module.SECRETS[("notion", "token")]: token})
        ok(f"token saved — in {secrets}")
    if config_module.write_notion_value(configuration.path, "workspace", report.workspace):
        ok(f"workspace = {report.workspace} — written to {configuration.path}")
    else:
        ok(f"workspace already pointed here ({report.workspace})")
    if configuration.notion.tickets_database:
        warn(
            "notion.tickets_database is still set and wins over the workspace — "
            "clear it unless you meant it"
        )

    print(
        f"\n{BOLD}ready.{RESET}\n\n"
        f"  Check it end to end:\n\n    {BOLD}ponos doctor{RESET}\n\n"
        f"  {DIM}board{RESET}    {target.url}\n"
        f"  {DIM}next{RESET}     write a ticket, move it to "
        f"“{configuration.notion.state('ready')}”, and wait for the next pass\n"
    )
    return 0


def _kept(message: str) -> None:
    """Already there, and left alone. Worth one dim line, not a green tick."""
    print(f"  {DIM}·{RESET} {message}")


def _timer_line(timer: systemd.Timer) -> None:
    """One line for the timer, and it is red when the timer will never fire.

    `enabled` is what `is-enabled` says, and it stayed true for the two hours the
    runner was silent: the timer was loaded, active, and had no next run. That
    state is the fault, and it is the only visible sign of it.
    """
    if timer.stalled:
        bad("ponos.timer: enabled, but no next run — it will never fire again")
        print(f"    {DIM}ponos enable   to restart it{RESET}")
    elif timer.enabled == "enabled":
        ok("ponos.timer: enabled" + (" — a run is in progress" if timer.running else ""))
    else:
        warn(f"ponos.timer: {timer.enabled}")
    if timer.row:
        print(f"    {DIM}{timer.row}{RESET}")


# What a group of checks is called on a terminal.
GROUP_TITLES = {
    "notion": "Board",
    "github": "GitHub",
    "claude": "Claude",
    "projects": "Projects",
    "machine": "Machine",
    "settings": "Settings",
}


def command_doctor(args: argparse.Namespace) -> int:
    """The checks of `health.py`, every one of them, said on a terminal."""
    title("Configuration")
    try:
        configuration = config_module.load()
        ok(f"{configuration.path}")
    except config_module.ConfigError as error:
        bad(str(error))
        return 2
    checks = health.run(configuration, remote=True)
    group = ""
    for check in checks:
        if check.group != group:
            group = check.group
            title(GROUP_TITLES.get(group, group))
        _doctor_line(check)
    problems = health.problems(checks)
    if problems:
        print(f"\n{RED}{problems} problem(s) to fix.{RESET}")
        return 1
    print(f"\n{GREEN}Everything is in place.{RESET}")
    return 0


def _doctor_line(check: health.Check) -> None:
    """One check: its verdict, and under one that is not green, why and what to do."""
    line = f"{check.text(check.title)}: {check.text(check.said)}"
    if check.state == health.INFO:
        print(f"  {DIM}{line}{RESET}")
    elif check.state == health.OK:
        ok(line)
    else:
        (bad if check.state == health.ERROR else warn)(line)
        if check.cause:
            print(f"    {DIM}{check.text(check.cause)}{RESET}")
        for step in check.steps:
            print(f"    {DIM}- {check.text(step)}{RESET}")
        if check.url:
            print(f"    {DIM}{check.url}{RESET}")
    for note in check.notes:
        print(f"    {DIM}“{note['name']}”: {'; '.join(note['said'])}{RESET}")
    for evidence in check.evidence.splitlines():
        print(f"    {DIM}{evidence}{RESET}")


def command_config(args: argparse.Namespace) -> int:
    path = config_module.config_path()
    if not path.exists():
        print(f"{path} does not exist — run install.sh again", file=sys.stderr)
        return 1
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    return subprocess.call([editor, str(path)])


def command_notify(args: argparse.Namespace) -> int:
    """Prove the channel works, before a question depends on it.

    A messaging channel is the one part of the runner that fails silently by
    design — nothing about a ticket goes wrong when the message does not
    arrive, you simply never hear about it. So it gets a command of its own,
    and it is the first thing to run after filling the token in.
    """
    try:
        configuration = config_module.load()
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 2
    settings = configuration.notify

    if args.pair:
        return _pair(configuration, settings)

    live = channels.open(settings)
    if not live:
        warn("no channel configured")
        print(
            f"  {DIM}[notify.telegram] token + chat, or [notify.slack] token + channel"
            f"\n  ponos config   to fill them in"
            f"\n  ponos notify --pair   to find your Telegram chat id{RESET}"
        )
        return 1

    text = args.message or (
        "Ponos speaking. Questions arrive here, and what you answer lands on the ticket."
    )
    problems = 0
    for channel in live:
        try:
            who = channel.check()
        except channels.ChannelError as error:
            bad(f"{channel.name} — {error}")
            problems += 1
            continue
        if channel.send(text):
            ok(f"{channel.name} — {who}")
        else:
            bad(f"{channel.name} — connected as {who}, but the message was refused")
            problems += 1
    if problems:
        return 1
    print(f"\n{DIM}replies come back on the next run (ponos run){RESET}")
    return 0


def _pair(configuration: config_module.Config, settings: config_module.Notify) -> int:
    """Find the Telegram chat id by reading who has written to the bot.

    A chat id is the one value of this configuration nobody can look up: the
    usual advice is to paste your token into somebody else's bot, which is the
    same as handing them the channel. Saying hello to your own bot and reading
    it back costs one GET and trusts no one.
    """
    from .channels import telegram as telegram_module

    token = settings.telegram.get("token", "")
    if not token:
        bad("[notify.telegram] token is not set")
        print(f"  {DIM}@BotFather → /newbot → paste the token into the configuration{RESET}")
        return 1
    try:
        found = telegram_module.chats(token)
    except channels.ChannelError as error:
        bad(f"Telegram refused: {error}")
        return 1
    if not found:
        warn("nobody has written to this bot in the last 24 hours")
        print(f"  {DIM}open the chat with your bot, say anything, and run this again{RESET}")
        return 1
    if len(found) > 1:
        warn(f"{len(found)} chats have written to this bot — pick one and set it by hand:")
        for identifier, name in found:
            print(f"  {identifier}  {DIM}{name}{RESET}")
        return 1
    identifier, name = found[0]
    config_module.write_value(configuration.path, "notify.telegram", "chat", identifier)
    ok(f"paired with “{name}” ({identifier}) — written to {configuration.path}")
    print(f"  {DIM}ponos notify   to send yourself a first message{RESET}")
    return 0


def _branch_kept(
    repo: Path, worktree: Path, branch: str, base: str, accounts: dict[str, str] | None = None
) -> str:
    """Why this branch must outlive its worktree — empty when nothing is lost.

    A branch is named after the ticket's ID, so it is the same one on every
    attempt: one left behind by a failure makes `add_worktree` refuse the ticket
    for good. Removing it is therefore the point of `clean` — but that refusal
    is also what protects a session's work, so the branch only goes when it is
    established that nobody else holds what is on it.
    """
    if git.has_ref(repo, f"origin/{branch}"):
        url = git.pull_request_on(repo, branch, accounts)
        if url:
            return f"it is pushed and its pull request is open — {url}"
    if not git.has_ref(repo, f"origin/{base}") and not git.has_ref(repo, base):
        return f"there is no {base} here to compare it against"
    ahead = git.commits_ahead(worktree, base)
    if ahead:
        return f"{ahead} commit(s) of its own are absent from {base}"
    if git.is_dirty(worktree):
        return "the worktree has changes that were never committed"
    return ""


def _sweep(directories: list[Path]) -> None:
    """Remove what `clean --force` was asked to, the run lock held."""
    try:
        configuration = config_module.load()
        configured_base, accounts = configuration.runner.base_branch, configuration.github
    except config_module.ConfigError:
        configured_base, accounts = "", {}
    for directory in directories:
        # Only a repository that lists this directory as one of its worktrees
        # is touched — see `git.repository_of`. Anything else is a directory,
        # and goes as one.
        repo = git.repository_of(directory)
        if not (repo and repo.exists()):
            if (directory / ".git").exists():
                shutil.rmtree(directory, ignore_errors=True)
                print(f"  removed {directory}")
                continue
            try:
                aside = git.discard(directory)
            except git.GitError as error:
                warn(str(error))
                continue
            print(f"  removed {directory}")
            if aside:
                print(f"    {DIM}not deletable by this user — moved to {aside}{RESET}")
            continue
        branch = git.git(["rev-parse", "--abbrev-ref", "HEAD"], directory).out
        # A detached HEAD names no branch — `HEAD` is what git answers then, and
        # there is nothing to remove afterwards.
        branch = "" if branch == "HEAD" else branch
        kept = (
            _branch_kept(
                repo, directory, branch, configured_base or git.default_branch(repo), accounts
            )
            if branch
            else ""
        )
        git.remove_worktree(repo, directory)
        print(f"  removed {directory}")
        if not branch:
            continue
        if kept:
            warn(f"branch {branch} kept — {kept}")
            print(
                f"    {DIM}that ticket cannot run again while it is there:"
                f" git -C {repo} branch -D {branch}{RESET}"
            )
            continue
        dropped = git.delete_branch(repo, branch)
        if dropped.ok:
            print(f"  removed branch {branch}")
        else:
            warn(f"branch {branch} kept — {dropped.err or dropped.out}")


def _clear_residues(directories: list[Path]) -> list[Path]:
    """Empty the worktree directories that are only residue; the others, untouched."""
    kept: list[Path] = []
    found = 0
    for directory in directories:
        if directory.parent.name != "worktrees" or not git.is_residue(directory):
            kept.append(directory)
            continue
        try:
            aside = git.discard(directory)
        except git.GitError as error:
            warn(str(error))
            kept.append(directory)
            continue
        found += 1
        print(f"  removed {directory}")
        if aside:
            print(f"    {DIM}not deletable by this user — moved to {aside}{RESET}")
    if found:
        print(f"  {found} residue(s) emptied")
    return kept


def _stray_work() -> tuple[list[leftovers.Project], list[tuple[int, str]]]:
    """The containers and processes still running from a worktree."""
    root = leftovers.worktrees()
    return leftovers.compose_projects(root), leftovers.processes(root)


def _report_stray_work(projects: list[leftovers.Project], held: list[tuple[int, str]]) -> None:
    for project in projects:
        warn(f"compose project {project.name} still has containers — {project.directory}")
    for pid, command in held:
        warn(f"process {pid} still runs in a worktree — {command[:100]}")


def _stop_stray_work() -> int:
    """Stop what a session left running, once the run lock says no session is in progress."""
    projects, held = _stray_work()
    if not projects and not held:
        return 0
    title(f"{len(projects)} compose project(s), {len(held)} process(es) left running")
    _report_stray_work(projects, held)
    try:
        with state.lock():
            for project in projects:
                if leftovers.stop_project(project):
                    ok(f"compose project {project.name} brought down")
                else:
                    bad(f"compose project {project.name} could not be brought down")
            leftovers.kill([pid for pid, _ in held])
    except state.Busy:
        bad("a run is in progress, and these may be the ones it works with")
        return 1
    return 0


def command_clean(args: argparse.Namespace) -> int:
    """Remove what failures left behind: worktrees, branches and scratch dirs."""
    if args.force and _stop_stray_work():
        return 1
    state_root = config_module.state_dir()
    directories = [
        directory
        for parent in ("worktrees", "scratch")
        if (state_root / parent).exists()
        for directory in sorted((state_root / parent).iterdir())
    ]
    # Residue first, forced or not: a directory with no `.git` holds nothing
    # git could lose, only what containers wrote there as root. Emptying it asks
    # nothing of the user, so the list below is only what could be somebody's work.
    try:
        with state.lock():
            directories = _clear_residues(directories)
    except state.Busy:
        pass  # the sweep below says so, when it is asked to remove anything
    if not directories:
        if not args.force:
            _report_stray_work(*_stray_work())
        print("Nothing left behind.")
        return 0
    title(f"{len(directories)} directory(ies) kept")
    for directory in directories:
        repo = git.repository_of(directory)
        branch = git.git(["rev-parse", "--abbrev-ref", "HEAD"], directory).out if repo else ""
        print(f"  {directory}  {DIM}{branch or 'no repository'}{RESET}")
    if not args.force:
        _report_stray_work(*_stray_work())
        print(f"\n{DIM}ponos clean --force to remove them{RESET}")
        return 0
    # Under the run lock, or not at all: a worktree kept by a failure and the
    # worktree a session is working in right now sit side by side, and nothing
    # on disk tells them apart. A run in progress is the one moment `clean`
    # must not choose between them.
    try:
        with state.lock():
            _sweep(directories)
            removed = state.prune_logs(args.days)
            if removed:
                print(f"  removed {removed} log file(s) older than {args.days} days")
            # The scratch directory a conversation runs in, for a ticket with no
            # repository. Kept while the runner still remembers the page — that
            # is what makes the next question land in the same Claude session.
            talks = conversation.clean_talks(
                {short_id(page) for page in conversation.Ledger.load().known_pages()}
            )
            if talks:
                print(f"  removed {talks} conversation directory(ies)")
    except state.Busy:
        bad("a run is in progress, and some of these are the worktrees it works in")
        print(f"  {DIM}try again once it has finished — ponos status says when{RESET}")
        return 1
    return 0


def command_update(args: argparse.Namespace) -> int:
    """What a run does once an hour, on demand and out loud."""
    if args.environment:
        return _remake_environment()
    try:
        settings = config_module.load().runner
    except config_module.ConfigError:
        settings = config_module.Runner()
    status = update_module.check(channel=settings.update_channel)
    if status.reason:
        bad(status.reason)
        return 1
    if not status.stale:
        newest = f"{status.tag}, " if status.tag else ""
        ok(f"already on the newest version ({newest}{status.current[:8]})")
        return 0
    print(f"  {update_module.describe(status)}")
    if args.check:
        print(f"  {DIM}ponos update to apply it{RESET}")
        return 0
    error = update_module.apply(status, settings.interval_seconds)
    if error:
        bad(error)
        return 1
    ok(f"updated to {status.tag or status.latest[:8]}")
    return 0


def _remake_environment() -> int:
    """`ponos update --environment`: the `.venv` of the version in use, made again.

    What `ponos doctor` prints when it is missing, outlived its Python, or lost
    a package. Made beside and renamed into place, as for a new version.
    """
    if config_module.in_container():
        bad(update_module.CONTAINER)
        return 1
    version = update_module.installed_version()
    if version is None:
        where = update_module.app_dir()
        bad(f"{where} was not installed by install.sh: it has no environment of its own")
        return 1
    problem = environment.create(version)
    if problem:
        bad(problem)
        return 1
    state, said = environment.diagnose(version)
    (ok if state == "ok" else warn)(said)
    return 0


def command_open(args: argparse.Namespace) -> int:
    """Handle a ponos:// link. The desktop calls this on a click."""
    try:
        return session.open_link(args.uri)
    except (ValueError, FileNotFoundError) as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 1


def command_serve(args: argparse.Namespace) -> int:
    """The web console: the board, this CLI and a chat, in one page."""
    from . import web

    # Before the configuration: what is signed out is the state's, not the file's.
    if getattr(args, "sign_out_everywhere", False):
        from .web import oauth, sessions

        sessions.revoke()
        ok("every browser signed in to the console is signed out — the token still opens it")
        ok(
            f"every connector signed in over OAuth is signed out — {oauth.revoke_connectors()} key(s) taken back"
        )
        drawn = [
            client
            for client in oauth.clients()
            if client["id"].startswith(oauth.LOCAL_PREFIX) and client["scope"]
        ]
        for client in drawn:
            print(
                f"  {DIM}still good, drawn with ponos mcp token:{RESET} {client['id']} {client['name']}"
                f"  {DIM}— ponos mcp revoke {client['id']}{RESET}"
            )
        return 0
    # Loaded, not required to be usable: the console is where an installation
    # becomes usable — its first connection asks for the Notion token and the
    # page — so refusing to start without them made that page unreachable, and
    # the systemd unit restart forever on a fresh install. A file that is
    # missing or does not parse still stops it: there is nothing to edit then.
    try:
        configuration = config_module.load()
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 2
    if args.print_token:
        print(web.token(configuration))
        return 0
    return web.serve(configuration, host=args.host or "", port=args.port or 0)


def command_mcp(args: argparse.Namespace) -> int:
    """The MCP server's keys: draw one for Claude Code, list them, take one back.

    Here and not in the console: a key is a way in, and the command bar of the
    console is a way in already — drawing a second from it would be a door
    opening another.
    """
    from .web import mcp, oauth

    # The address to paste, on this machine: the console's port, wherever it was moved.
    try:
        web_settings = config_module.load().web
        port, public = web_settings.port, web_settings.url
    except config_module.ConfigError:
        port, public = 8787, ""
    address = f"http://127.0.0.1:{port}/mcp"
    try:
        if args.action == "token":
            identifier, token = oauth.local(args.name or "Claude Code", write=not args.read_only)
            scope = oauth.READ if args.read_only else f"{oauth.READ} {oauth.WRITE}"
            ok(f"token for {args.name or 'Claude Code'} ({scope}) — client {identifier}")
            print(f"\n  {token}\n")
            print(
                "Shown once, and kept only as a digest — for a client that cannot sign in itself:"
            )
            print(
                f'  claude mcp add --transport http ponos {address} --header "Authorization: Bearer {token}"'
            )
            print(
                f"{DIM}Claude Code needs none: claude mcp add --transport http ponos {address}{RESET}"
            )
            print(f"{DIM}Take it back with: ponos mcp revoke {identifier}{RESET}")
            return 0
        if args.action == "revoke":
            taken = oauth.revoke(args.client)
            ok(f"{args.client}: {taken} key(s) taken back")
            return 0
        clients = oauth.clients()
        title("Connect")
        if public:
            print(
                f"  {public}/mcp  {DIM}— claude.ai, Claude Desktop: paste it as a custom connector{RESET}"
            )
        print(f"  {address}")
        print(
            f"  {DIM}claude mcp add --transport http ponos {address}  — then /mcp, Authenticate{RESET}"
        )
        title("Clients")
        if not clients:
            print("  none yet — connect claude.ai, or: ponos mcp token")
        for client in clients:
            scope = client["scope"] or f"{DIM}no live key{RESET}"
            print(
                f"  {client['id']:<26} {client['name']:<24} {scope}  {DIM}{client['created_at']}{RESET}"
            )
        title("Last writes")
        calls = mcp.calls(args.number)
        if not calls:
            print("  none yet")
        for call in calls:
            colour = GREEN if call["outcome"] == "ok" else YELLOW
            print(
                f"  {call['at']}  {call['tool']:<16} {colour}{call['outcome']}{RESET}  {DIM}{call['name']} ({call['client']}){RESET}"
            )
            print(f"      {DIM}{call['arguments']}{RESET}")
    except LookupError as error:
        bad(str(error))
        return 1
    except db.ERRORS as error:
        bad(f"the local database: {error}")
        return 1
    return 0


def command_tailscale(args: argparse.Namespace) -> int:
    """The console inside the tailnet, the MCP endpoint through Funnel — see `tailscale.py`.

    `enable` is the decision to publish `/mcp`, which is why nothing else turns
    it on: not the installer, not an update, not `ponos enable`.
    """
    from . import tailscale

    try:
        port = config_module.load().web.port
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 2
    try:
        if args.action == "watch":
            tailscale.watch(port, args.interval)
            return 0
        if args.action == "enable":
            if not shutil.which("systemctl"):
                print(
                    "systemd not available — `ponos tailscale watch` does the same in the foreground",
                    file=sys.stderr,
                )
                return 1
            update_module.write_units(config_module.load().runner.interval_seconds)
            subprocess.call(["systemctl", "--user", "daemon-reload"])
            code = subprocess.call(
                ["systemctl", "--user", "enable", "--now", "ponos-tailscale.service"]
            )
            if code == 0:
                ok("ponos-tailscale.service enabled — it waits for the tailnet, then publishes")
                print(f"{DIM}  journalctl --user -u ponos-tailscale -f{RESET}")
            return code
        if args.action == "disable":
            if shutil.which("systemctl"):
                subprocess.call(
                    ["systemctl", "--user", "disable", "--now", "ponos-tailscale.service"]
                )
            tailscale.withdraw()
            ok("both doors taken down")
            return 0
        if args.action == "apply":
            tailscale.apply(port)
        current = tailscale.node()
        title("Tailnet")
        if not current.connected:
            warn(f"tailscale is {current.state} — `tailscale up`, then again")
            return 1
        up = tailscale.in_place(port, current.name)
        (ok if up else warn)(
            f"{current.name}: "
            + ("both doors are up" if up else "not published — `ponos tailscale apply`")
        )
        print(
            f"  console   https://{current.name}:{tailscale.PRIVATE_PORT}  {DIM}— tailnet only{RESET}"
        )
        print(
            f'  connector https://{current.name}/mcp  {DIM}— public, behind the keys; set web.url = "https://{current.name}"{RESET}'
        )
    except tailscale.TailscaleError as error:
        bad(str(error))
        return 1
    return 0


def command_timer(args: argparse.Namespace) -> int:
    """Both units at once: the timer that runs tickets, and the console.

    They are enabled and disabled together because they are the same answer to
    "is the runner on this machine running" — a console left behind by a
    `disable` would keep showing a board nothing is picking up.
    """
    if not shutil.which("systemctl"):
        print("systemd not available", file=sys.stderr)
        return 1
    if args.command == "disable":
        code = subprocess.call(["systemctl", "--user", "disable", "--now", "ponos.timer"])
        subprocess.call(["systemctl", "--user", "disable", "--now", "ponos-web.service"])
        # The public door goes with the console it opens onto.
        subprocess.call(
            ["systemctl", "--user", "disable", "--now", "ponos-tailscale.service"],
            stderr=subprocess.DEVNULL,
        )
        return code

    try:
        configuration = config_module.load()
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 2
    interval = configuration.runner.interval_seconds
    update_module.write_units(interval)
    subprocess.call(["systemctl", "--user", "daemon-reload"])
    # Enabled, then restarted rather than `--now`: a timer that is already
    # active is left alone by `--now`, and a timer left alone keeps the next
    # run it had — which, after the fault this exists to cure, is none. A
    # restart gives OnActiveSec its starting point; the service, if one is
    # running, is not the timer's to stop and carries on.
    code = subprocess.call(["systemctl", "--user", "enable", "ponos.timer"])
    if code == 0:
        code = subprocess.call(["systemctl", "--user", "restart", "ponos.timer"])
    if code == 0:
        every = f"{interval}s" if interval < 120 else f"{interval // 60} min"
        ok(f"timer enabled — one run every {every}")
    console = subprocess.call(["systemctl", "--user", "enable", "--now", "ponos-web.service"])
    if console == 0:
        ok(f"console enabled — http://{configuration.web.host}:{configuration.web.port}")
    else:
        warn("the console's unit refused to start — journalctl --user -u ponos-web")
    return code


# -- entry point -------------------------------------------------------------


def banner_lines() -> list[tuple[str, str]]:
    """What the frame holds: every line as (plain, coloured).

    The two are kept side by side because escape codes take no room on screen —
    a frame measured with them in it comes out crooked the moment colours are
    on, which is exactly when somebody is looking at it.
    """
    version = update_module.running()["version"]
    lines = [
        (
            f"{NAME} {version}",
            f"{BOLD}{NAME}{RESET} {GREEN}{version}{RESET}",
        ),
        (TAGLINE, f"{DIM}{TAGLINE}{RESET}"),
    ]
    # Read from the stamp a run already wrote, never by asking the remote: a
    # welcome screen is not the place to spend a network round trip.
    status = update_module.remembered()
    if status.stale:
        waiting = f"{status.latest[:8]} is waiting — ponos update"
        lines.append((waiting, f"{YELLOW}{waiting}{RESET}"))
    return lines


def banner() -> str:
    """The product and its version, framed."""
    lines = banner_lines()
    width = max(len(plain) for plain, _ in lines)
    drawn = [f"  {DIM}╭─{'─' * width}─╮{RESET}"]
    for plain, coloured in lines:
        drawn.append(f"  {DIM}│{RESET} {coloured}{' ' * (width - len(plain))} {DIM}│{RESET}")
    drawn.append(f"  {DIM}╰─{'─' * width}─╯{RESET}")
    return "\n".join(drawn)


def commands_of(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    """Every verb and the one line that says what it does, in the order declared."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return [(choice.dest, choice.help or "") for choice in action._choices_actions]
    return []


def welcome(parser: argparse.ArgumentParser) -> None:
    """What a bare `ponos` shows: the product, its version, its verbs.

    Not argparse's usage block. Somebody typing the name alone is looking at
    the thing for the first time, or checking what they installed — both are
    answered better by the version and a list of commands in plain columns.
    """
    print()
    print(banner())
    print()
    commands = commands_of(parser)
    width = max((len(name) for name, _ in commands), default=0)
    title("  Commands")
    for name, help_text in commands:
        print(f"    {name.ljust(width)}  {DIM}{help_text}{RESET}")
    print()
    print(f"  {DIM}ponos <command> --help says what a command takes.{RESET}")
    print(f"  {DIM}Start with:{RESET} ponos doctor")
    spoken = board_language()
    if spoken != voice.DEFAULT:
        print(
            f"  {DIM}The CLI speaks English; the console follows runner.language ({spoken}).{RESET}"
        )
    print()


def board_language() -> str:
    """The language the file asks the console and the reports for — English when it says none.

    The CLI itself stays in English, whatever the file says: it is read by
    whoever stands at the machine, and half of it is argparse's and git's.
    The welcome screen says so rather than leave somebody who set
    `language = "fr"` wondering whether the setting was read. A file that
    cannot be read is no reason to refuse a welcome: it is English then.
    """
    try:
        return voice.understood(config_module.load().runner.interface_language())
    except (config_module.ConfigError, OSError):
        return voice.DEFAULT


class VersionAction(argparse.Action):
    """`--version`: the number, and the commit when the number alone does not say it.

    Asked of git only when the flag is given — every other command builds the
    same parser, and has no use for a version read at each start.
    """

    def __init__(self, option_strings: list[str], dest: str = argparse.SUPPRESS, **_: Any) -> None:
        super().__init__(
            option_strings,
            dest,
            nargs=0,
            default=argparse.SUPPRESS,
            help="show program's version number and exit",
        )

    def __call__(self, parser: argparse.ArgumentParser, *_: Any) -> None:
        print(f"{PRODUCT} {update_module.running()['version']}")
        parser.exit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRODUCT,
        description=TAGLINE,
    )
    parser.add_argument("--version", action=VersionAction)
    subparsers = parser.add_subparsers(dest="command", help="the command to run")

    run = subparsers.add_parser("run", help="handle the ready tickets (one run)")
    run.add_argument("--ticket", help="URL or ID of one ticket, whatever its status")
    run.add_argument("--limit", type=int, help="maximum number of tickets for this run")
    run.add_argument("--dry-run", action="store_true", help="show without changing anything")
    run.add_argument(
        "--every",
        type=int,
        nargs="?",
        const=0,
        metavar="SECONDS",
        help="keep running, one run every SECONDS (default: runner.interval_seconds) — "
        "the timer, where there is no systemd",
    )
    run.set_defaults(function=command_run)

    listing = subparsers.add_parser("list", help="list the ready tickets")
    listing.set_defaults(function=command_list)

    scheduling = subparsers.add_parser("schedules", help="what comes back on its own, and when")
    scheduling.add_argument("--run", metavar="NAME", help="make its ticket now, without waiting")
    scheduling.add_argument(
        "--force", action="store_true", help="with --run: even if the last one is still open"
    )
    scheduling.set_defaults(function=command_schedules)

    typing = subparsers.add_parser("subtypes", help="the sub-types of the code tickets")
    typing.add_argument(
        "--backfill", action="store_true", help="fill the empty ones from the title's prefix"
    )
    typing.add_argument("--dry-run", action="store_true", help="with --backfill: write nothing")
    typing.add_argument(
        "--all",
        action="store_true",
        help="with --backfill: done and cancelled tickets too — their closing date in the "
        "statistics becomes today",
    )
    typing.set_defaults(function=command_subtypes)

    projects = subparsers.add_parser("projects", help="check the project → repository mapping")
    projects.set_defaults(function=command_projects)

    syncing = subparsers.add_parser("sync", help="reconcile the Notion board and the Markdown one")
    syncing.add_argument(
        "--journal", action="store_true", help="show what past reconciliations did"
    )
    syncing.add_argument("-n", "--number", type=int, default=30, help="with --journal: how many")
    syncing.set_defaults(function=command_sync)

    status = subparsers.add_parser("status", help="timer, console, current run, recent tickets")
    status.set_defaults(function=command_status)

    history = subparsers.add_parser("history", help="tickets already handled")
    history.add_argument(
        "-n", "--number", type=int, default=20, help="how many tickets to show (default: 20)"
    )
    history.set_defaults(function=command_history)

    logs = subparsers.add_parser("logs", help="show a session's log (-f to follow)")
    logs.add_argument("ticket", nargs="?", help="the ticket's ID, in any form")
    logs.add_argument(
        "-f", "--follow", action="store_true", help="keep printing what is written, until Ctrl-C"
    )
    logs.add_argument("--raw", action="store_true", help="the raw JSON stream")
    logs.add_argument(
        "--runs", action="store_true", help="list the ticket's runs from the local journal"
    )
    logs.add_argument(
        "--service",
        action="store_true",
        help="the runner's and the console's own log, ponos.log, instead of a session",
    )
    logs.set_defaults(function=command_logs)

    doctor = subparsers.add_parser("doctor", help="full diagnostics")
    doctor.set_defaults(function=command_doctor)

    initialise = subparsers.add_parser(
        "init", help="create the Notion databases from one page link"
    )
    initialise.add_argument("page", help="URL of the Notion page to build under")
    initialise.add_argument("--token", help="Notion integration token, saved to the configuration")
    initialise.add_argument(
        "--no-demo", action="store_true", help="do not create the demonstration ticket"
    )
    initialise.set_defaults(function=command_init)

    configure = subparsers.add_parser("config", help="open the configuration")
    configure.set_defaults(function=command_config)

    updating = subparsers.add_parser("update", help="move the installation to the newest version")
    updating.add_argument(
        "--check", action="store_true", help="say what is available, change nothing"
    )
    updating.add_argument(
        "--environment",
        action="store_true",
        help="make the environment of the version in use again, and nothing else",
    )
    updating.set_defaults(function=command_update)

    opener = subparsers.add_parser("open", help="open a ponos:// session link")
    opener.add_argument("uri", help="ponos://session/<id>?cwd=<path>")
    opener.set_defaults(function=command_open)

    serving = subparsers.add_parser("serve", help="the web console: board, command line and chat")
    serving.add_argument("--host", help="what to bind (default: web.host, 127.0.0.1)")
    serving.add_argument("--port", type=int, help="what port to listen on (default: web.port)")
    serving.add_argument(
        "--print-token", action="store_true", help="print the console's token and exit"
    )
    serving.add_argument(
        "--sign-out-everywhere",
        action="store_true",
        help="end every browser's and every OAuth connector's sign-in to the console, and exit",
    )
    serving.set_defaults(function=command_serve)

    serving_mcp = subparsers.add_parser(
        "mcp", help="the MCP server's keys: draw, list, revoke (default: list)"
    )
    actions = serving_mcp.add_subparsers(dest="action", help="what to do (default: list)")
    drawing = actions.add_parser("token", help="draw a token for Claude Code")
    drawing.add_argument("--name", help="who it is for, as the journal will say it")
    drawing.add_argument("--read-only", action="store_true", help="read, never write")
    revoking = actions.add_parser("revoke", help="take back every key of one client")
    revoking.add_argument("client", help="the client's id, as `ponos mcp list` shows it")
    listing_keys = actions.add_parser(
        "list", help="the clients, and the last writes they asked for"
    )
    listing_keys.add_argument(
        "-n", "--number", type=int, default=20, help="how many writes to show (default: 20)"
    )
    serving_mcp.set_defaults(function=command_mcp, action="list", number=20)

    tailnet = subparsers.add_parser(
        "tailscale", help="the console on your tailnet, the MCP connector through Funnel"
    )
    tailnet.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("status", "apply", "enable", "disable", "watch"),
        help="status (default), apply once, enable the unit, disable and withdraw, or watch",
    )
    tailnet.add_argument(
        "--interval", type=int, default=30, help="seconds between two looks (watch)"
    )
    tailnet.set_defaults(function=command_tailscale)

    notifying = subparsers.add_parser(
        "notify", help="send yourself a test message, or pair a Telegram chat"
    )
    notifying.add_argument("message", nargs="?", help="what to send (default: a test line)")
    notifying.add_argument(
        "--pair", action="store_true", help="find the Telegram chat id and save it"
    )
    notifying.set_defaults(function=command_notify)

    clean = subparsers.add_parser("clean", help="remove worktrees left by failures")
    clean.add_argument(
        "--force",
        action="store_true",
        help="remove the worktrees and scratch directories listed — uncommitted changes go "
        "with them — their branches and the logs older than --days, and stop the containers "
        "and processes they left running; keeps a branch pushed with an open pull request, or "
        "whose worktree held commits absent from the base or uncommitted changes",
    )
    clean.add_argument("--days", type=int, default=14, help="also drop logs older than this")
    clean.set_defaults(function=command_clean)

    for name, help_text in (
        ("enable", "apply runner.interval_seconds, start the timer and the console"),
        ("disable", "stop the timer and the console"),
    ):
        timer = subparsers.add_parser(name, help=help_text)
        timer.set_defaults(function=command_timer)

    return parser


def subcommands() -> tuple[str, ...]:
    """The verbs this parser offers — which is what the console is allowed to run.

    Read from the parser rather than written down a second time: a command added
    above is a command the web console offers, without anybody having to
    remember to say so twice.
    """
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return tuple(sorted(action.choices))
    return ()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "function", None):
        welcome(parser)
        return 0
    # Whatever the command, what it logs is kept in ponos.log — see log.py.
    log.setup()
    try:
        code: int = args.function(args)
        return code
    except KeyboardInterrupt:
        return 130


def secrets_out_of_config(say: Callable[[str], None] | None = None) -> None:
    """Move the secrets `config.toml` still holds into `secrets.env`, and say so.

    Said on stderr, once — the launch that moves them is the only one that has
    something to say. A move that cannot be made, a read-only file in an image,
    is said at every launch instead, with the names to set: the runner ignores
    what is left there, and would otherwise only report a missing token.

    The console's password, once in `secrets.env`, is replaced by its digest
    there (`config.hash_password`): the same launch, for the same reason.
    """
    say = say or (lambda line: print(line, file=sys.stderr))
    path = config_module.config_path()
    target = config_module.secrets_path(path)
    try:
        moved = config_module.move_secrets(path)
    except OSError as error:
        moved = []
        say(f"ponos: could not move the secrets out of {path}: {error.strerror or error}")
    if moved:
        say(
            f"ponos: moved {', '.join(moved)} out of {path} into {target} (0600) — "
            "config.toml holds no secret any more"
        )
    try:
        if config_module.hash_password(path):
            say(
                f"ponos: the console's password in {target} is kept as a scrypt digest now — "
                "the same password signs in"
            )
    except OSError as error:
        say(
            f"ponos: could not replace the console's password in {target} by its digest: "
            f"{error.strerror or error}"
        )
    left = config_module.exposed(config_module.read_raw(path))
    if left:
        names = ", ".join(
            f"{table}.{key} → {config_module.SECRETS[(table, key)]}" for table, key in left
        )
        say(
            f"ponos: {path} still holds secrets, and they are ignored — set them in "
            f"{target} or in the environment instead: {names}"
        )
    try:
        loose = target.stat().st_mode & 0o077
    except OSError:
        loose = 0
    if loose:
        say(f"ponos: {target} can be read by others — chmod 600 {target}")


if __name__ == "__main__":
    # Here rather than in `main`, which the tests call: only a real launch
    # moves an installation's directories, or its secrets — and only a real
    # launch from a checkout is kept off the real state.
    try:
        config_module.refuse_real_state()
    except config_module.RealStateRefused as error:
        print(f"ponos: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    legacy.migrate()
    config_module.private_state()
    secrets_out_of_config()
    raise SystemExit(main())
