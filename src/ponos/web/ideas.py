"""Finding ideas from the console, and turning the kept ones into board pages.

`ideas.py` knows what an idea is and remembers it; this is the half that
reaches out — one session to propose a batch, the board to read what is
already there and to write a kept idea onto it. It holds no state of its own
beyond the lock that keeps two batches for the same scope from being asked
for at once: the second click of an impatient person would otherwise pay for
ten ideas the first one was already writing.

An idea turned into a ticket goes through `Api.create_ticket`, the console's own "New ticket",
as a draft with no model: the same road as a ticket typed by hand, so that it
reads the same on the board and the runner treats it the same way — classified
and given a model when somebody moves it to ready, not before.

An idea written or reworded by hand is signed by whoever `gh` is signed in as
— the name and the picture of the GitHub account pull requests are opened
from, which is the closest thing to a person a console behind one password
knows — or by git's `user.name` where there is no `gh`. Asked once per
process: it does not change while the console runs.

An idea written by hand is scored behind the answer that saved it: the light
model takes seconds, and the form has closed long before. The ideas already
there, from before scores, are scored on request, a scope at a time and twenty
to a call, each call capped at what `ideas.SCORE_CEILING_USD` allows — so the
sum said before it starts is a ceiling, not a guess. One such pass at a time:
the second click would pay for scores the first is already writing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .. import ideas, provider, session, state, store
from ..config import state_dir

if TYPE_CHECKING:
    from .api import Api

# The README is read for what the project is; these are the names it goes by.
READMES = ("README.md", "README", "readme.md", "README.rst", "README.txt")

# How many decisions the history tab shows: enough to find the one you doubt.
HISTORY = 50

# `gh` asks GitHub, which is a request away: past this, the idea is signed as "you".
WHO_TIMEOUT = 5

# Language names as the prompt says them — see `voice.understood`.
LANGUAGES = {"en": "English", "fr": "French"}

# What `_busy` holds while ideas already there are being scored: no scope has
# this id, since a page id is hexadecimal.
SCORING = "scoring"


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="ponos-idea-scores", daemon=True).start()


class ScoreFailed(Exception):
    """A scoring call that gave no score, and the reason in a sentence — kept on the ideas it was for."""


class Ideas:
    def __init__(self, api: Api) -> None:
        self._api = api
        self._lock = threading.Lock()
        self._busy: set[str] = set()
        self._person: tuple[str, str] | None = None
        # How work that should not hold up an answer is run: a thread of its
        # own here, and in place in a test, which wants to read what it wrote.
        self.later: Callable[[Callable[[], None]], None] = _thread

    # -- reading --------------------------------------------------------------

    def proposed(self, project: str = "") -> dict:
        """The ideas still waiting for a decision in one scope, and what finding them cost."""
        project = ideas.bare(project)
        batches, cost = ideas.spent(project)
        last = ideas.last_decided(project)
        return {
            "scope": ideas.scope_of(project),
            "project": project,
            "ideas": [idea.shown() for idea in ideas.listed(project)],
            "decided": [idea.shown() for idea in self._decided(project)],
            "batches": batches,
            "cost_usd": round(cost, 6),
            "undo": last.shown() if last else None,
        }

    def every(self, project: str | None = "") -> dict:
        """Every idea of one scope, thrown away and turned into tickets included,
        and how many there are in each status — the list on a project's page.
        With None, those of every scope at once: the Ideas page's."""
        project = None if project is None else ideas.bare(project)
        found = ideas.every(project)
        counts = {status: 0 for status in ideas.STATUSES}
        for idea in found:
            counts[idea.status] = counts.get(idea.status, 0) + 1
        return {
            "scope": "all" if project is None else ideas.scope_of(project),
            "project": project or "",
            "ideas": [idea.shown() for idea in found],
            "counts": counts,
        }

    @staticmethod
    def _decided(project: str) -> list[ideas.Idea]:
        """The last ideas decided on, the most recent first: the history tab's."""
        decided = ideas.listed(project, ("kept", "discarded", "ticket"))
        decided.sort(key=lambda idea: (idea.decided_at or "", idea.id), reverse=True)
        return decided[:HISTORY]

    # -- finding --------------------------------------------------------------

    def generate(self, project: str = "") -> dict:
        """Ask for one batch, store what is new in it, and say what it cost.

        Raises RuntimeError when a batch for the same scope is already being
        written, and when the subscription is out of credit — the server's 409.
        """
        project = ideas.bare(project)
        with self._lock:
            if project in self._busy:
                raise RuntimeError("ideas are already being found for this scope")
            self._busy.add(project)
        try:
            return self._generate(project)
        finally:
            with self._lock:
                self._busy.discard(project)

    def _about(self, project: str, *, readme: bool = True) -> tuple[str, str, str, list[str], str]:
        """What a scope is: its name, its brief and its README for a project;
        the names of every project and the workspace's context for the workspace."""
        api = self._api
        name, brief, text = "", "", ""
        names: list[str] = []
        context = ""
        if project:
            # The list's row rather than the board's: it carries the path the
            # configuration maps the project to, which is where its README is.
            row = next(
                (row for row in api.all_projects()["projects"] if row["id"] == project), None
            )
            if row is None:
                raise LookupError(f"no project with id {project}")
            name = row["name"]
            brief = api.runner.resolver.brief(api.runner.client, project)
            if readme:
                text = _readme(
                    api.runner.resolver.locate(
                        name,
                        row.get("configured") or row.get("path") or "",
                        row.get("repository") or "",
                    )
                )
        else:
            names = sorted((row["name"] for row in api.projects().values()), key=str.lower)
            try:
                context = api.runner.workspace.context
            except store.StoreError:
                context = ""
        return name, brief, text, names, context

    def _generate(self, project: str) -> dict:
        api = self._api
        configuration = api.config
        name, brief, readme, names, context = self._about(project)
        tickets = self._tickets(name if project else "")
        known = ideas.known(project)
        model = configuration.runner.allowed(configuration.runner.ideas_model)
        asked = ideas.prompt(
            project=name,
            brief=brief,
            readme=readme,
            tickets=tickets,
            projects=names,
            context=context,
            known=known,
            language=LANGUAGES.get(api.runner.voice.language, "English"),
        )

        estimate = ideas.score_estimate(asked)
        if estimate > ideas.SCORE_CEILING_USD:
            raise ScoreFailed(
                f"The prompt would cost about ${estimate:.2f}, over the ${ideas.SCORE_CEILING_USD:.2f} a call may spend"
            )
        short = (project or "global")[:8]
        workdir = state_dir() / "scratch" / f"ideas-{short}-{uuid.uuid4().hex[:6]}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = session.run(
                asked,
                cwd=workdir,
                log=state.log_file(f"ideas-{short}"),
                model=model,
                # It reads what it is given and answers one array: the mode a
                # conversation runs in is more than it needs.
                permission_mode=configuration.runner.reply_permission_mode,
                timeout_minutes=ideas.TIMEOUT_MINUTES,
                environment=provider.environment(configuration),
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        if outcome.exhausted:
            ideas.record(project, model, outcome.cost_usd or None, [], "out of credit")
            raise RuntimeError("out of credit — try again once it is back")
        found = ideas.parse(outcome.answer, ideas.scope_of(project)) if outcome.ok else []
        kept, dropped = ideas.fresh(found, [*known, *(title for title, _ in tickets)])
        error = "" if kept else (outcome.error or "the session proposed nothing new")
        batch, stored = ideas.record(project, model, outcome.cost_usd, kept[: ideas.BATCH], error)
        api.hub.publish("ideas", project=project, batch=batch)
        return {
            "batch": batch,
            "ideas": [idea.shown() for idea in stored],
            "dropped": [candidate["title"] for candidate in dropped],
            "cost_usd": outcome.cost_usd,
            "model": model,
            "error": error,
        }

    def _tickets(self, project: str) -> list[tuple[str, str]]:
        """The latest tickets of a project — of the board, for the workspace.

        Latest first, every column but the drafts and those nobody named: what
        has been done and what is being done is what an idea must not repeat.
        A board that cannot be read leaves the prompt without them, not the
        batch without its ideas.
        """
        try:
            tickets = self._api.board()["tickets"]
        except store.StoreError:
            return []
        chosen = [
            ticket
            for ticket in tickets
            if ticket["title"]
            and ticket["column"] != "draft"
            and (not project or ticket["project"] == project)
        ]
        chosen.sort(key=lambda ticket: ticket.get("edited") or "", reverse=True)
        return [
            (
                ticket["title"],
                ticket["column"]
                if project or not ticket["project"]
                else f"{ticket['column']}, {ticket['project']}",
            )
            for ticket in chosen[: ideas.TICKETS_SHOWN]
        ]

    # -- scoring --------------------------------------------------------------

    def unscored(self, project: str | None = None) -> dict:
        """How many ideas have no score yet, and what scoring them may cost at most.

        With None, those of every scope — the Ideas page's.
        """
        waiting = ideas.unscored(project)
        calls = sum(-(-len(group) // ideas.SCORE_BATCH) for group in _by_scope(waiting).values())
        configuration = self._api.config
        with self._lock:
            busy = SCORING in self._busy
        return {
            "count": len(waiting),
            "calls": calls,
            "ceiling_usd": round(calls * ideas.SCORE_CEILING_USD, 2),
            "model": configuration.runner.allowed(configuration.runner.classify_model),
            "running": busy,
        }

    def score_unscored(self, project: str | None = None) -> dict:
        """Score every idea that has none, behind the answer: say what was started.

        Raises RuntimeError when a pass is already scoring — the server's 409.
        """
        with self._lock:
            if SCORING in self._busy:
                raise RuntimeError("ideas are already being scored")
            self._busy.add(SCORING)

        def done() -> None:
            with self._lock:
                self._busy.discard(SCORING)

        try:
            waiting = ideas.unscored(project)
            for idea in waiting:
                ideas.scoring(idea.id)
            if waiting:
                self._api.hub.publish("ideas", project=project or "", scoring=len(waiting))
            started = self.unscored(project)
        except Exception:
            done()
            raise

        def work() -> None:
            failures: list[str] = []
            try:
                self.score([idea.id for idea in waiting], failures)
            finally:
                done()
                if failures:
                    self._api.hub.publish("ideas", project=project or "", failed=failures[0])

        self.later(work)
        return started

    def score(self, identifiers: list[int], failures: list[str] | None = None) -> dict[int, int]:
        """Score these ideas on the light model, a scope and twenty at a time.

        What a call left without a score is no longer said to be scored — it
        is not scored, and can be asked for again. Never raises: nobody is
        waiting on it but the list, which reads the outcome when it is told to.
        Why a call failed stays on its ideas (`detail["score_error"]`), goes to
        the console's journal, and is added to `failures` for whoever asked.
        """
        found: dict[int, int] = {}
        chosen: list[ideas.Idea] = []
        for identifier in identifiers:
            try:
                chosen.append(ideas.get(identifier))
            except LookupError:
                continue
        for project, group in _by_scope(chosen).items():
            for start in range(0, len(group), ideas.SCORE_BATCH):
                chunk = group[start : start + ideas.SCORE_BATCH]
                error = ""
                try:
                    scores = self._score(project, chunk)
                except ScoreFailed as failure:
                    scores, error = {}, str(failure)
                except Exception as failure:  # noqa: BLE001 — a score is never worth a crash
                    scores, error = {}, f"{type(failure).__name__}: {failure}"
                if error:
                    print(
                        f"ideas: scoring {len(chunk)} ideas of {project or 'the workspace'} failed: {error}",
                        file=sys.stderr,
                    )
                    if failures is not None:
                        failures.append(error)
                for idea in chunk:
                    score, reason = scores.get(idea.id, (None, ""))
                    try:
                        ideas.scored(
                            idea.id,
                            score,
                            reason,
                            error
                            or ("The answer had no score for this idea" if score is None else ""),
                        )
                    except LookupError:
                        continue
                    if score is not None:
                        found[idea.id] = score
                self._api.hub.publish("ideas", project=project, scored=len(chunk))
        return found

    def _score(self, project: str, chunk: list[ideas.Idea]) -> dict[int, tuple[int, str]]:
        api = self._api
        configuration = api.config
        name, brief, _, _, context = self._about(project, readme=False)
        asked = ideas.score_prompt(
            chunk,
            project=name,
            brief=brief,
            tickets=self._tickets(name if project else ""),
            context=context,
            known=ideas.known(project),
            language=LANGUAGES.get(api.runner.voice.language, "English"),
        )
        estimate = ideas.score_estimate(asked)
        if estimate > ideas.SCORE_CEILING_USD:
            raise ScoreFailed(
                f"The prompt would cost about ${estimate:.2f}, over the ${ideas.SCORE_CEILING_USD:.2f} a call may spend"
            )
        short = (project or "global")[:8]
        workdir = state_dir() / "scratch" / f"scores-{short}-{uuid.uuid4().hex[:6]}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = session.run(
                asked,
                cwd=workdir,
                log=state.log_file(f"scores-{short}"),
                model=configuration.runner.allowed(configuration.runner.classify_model),
                permission_mode=configuration.runner.reply_permission_mode,
                timeout_minutes=ideas.SCORE_TIMEOUT_MINUTES,
                max_budget_usd=ideas.SCORE_CEILING_USD,
                environment=provider.environment(configuration),
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if outcome.over_budget:
            raise ScoreFailed(
                f"Stopped at the ${ideas.SCORE_CEILING_USD:.2f} a call may spend (${outcome.cost_usd:.2f} spent)"
            )
        if outcome.exhausted:
            raise ScoreFailed("The credits are spent")
        if outcome.stopped or not outcome.ok:
            raise ScoreFailed(outcome.error or outcome.summary or "The session did not end well")
        found = ideas.parse_scores(outcome.answer, [idea.id for idea in chunk])
        if not found:
            raise ScoreFailed("The answer could not be read as scores")
        return found

    def _score_later(self, idea: ideas.Idea) -> None:
        """Score one idea written by hand, behind the answer that saved it."""
        ideas.scoring(idea.id)
        self.later(lambda: self.score([idea.id]))

    # -- deciding -------------------------------------------------------------

    def ticket(self, identifier: int) -> dict:
        """Turn an idea into a draft ticket, or a new project and its first ticket.

        An idea turned into one before — and taken back since — already has its
        pages: they are what it becomes again, rather than a second copy of them.
        """
        idea = ideas.get(identifier)
        if idea.status == "ticket":
            return idea.shown()
        api = self._api
        say = api.runner.voice.say
        created, ticket = idea.created, idea.ticket
        if idea.kind == "project":
            if not created:
                database = api.runner.workspace.projects
                if not database:
                    raise ValueError("this workspace has no projects database")
                created = ideas.bare(api.runner.client.create_row(database, idea.title, {}))
                if idea.description.strip():
                    api.runner.client.append_markdown(created, idea.description.strip())
                api.forget_projects()
                api.hub.publish("projects", saved=created)
            if not ticket:
                ticket = api.create_ticket(
                    say("idea-frame", name=idea.title),
                    ideas.framing(idea, say),
                    project=created,
                    ready=False,
                )["id"]
        elif not ticket:
            ticket = api.create_ticket(
                idea.title, ideas.body(idea, say), project=idea.project, ready=False
            )["id"]
        made = ideas.decide(identifier, "ticket", ticket=ideas.bare(ticket), created=created)
        api.hub.publish("ideas", project=idea.project, ticket=identifier)
        return made.shown()

    def keep(self, identifier: int) -> dict:
        """Keep an idea for later: a decision, and nothing on the board yet."""
        return self._mark(identifier, "kept")

    def discard(self, identifier: int) -> dict:
        """Throw an idea away. Nothing else: it stays known, never to be proposed again."""
        return self._mark(identifier, "discarded")

    def reopen(self, identifier: int) -> dict:
        """Make an idea new again, whatever was decided about it.

        One that became a ticket leaves its ticket on the board, as `undo` does.
        """
        idea = ideas.get(identifier)
        back = ideas.decide(identifier, "proposed")
        self._api.hub.publish("ideas", project=idea.project, reopened=identifier)
        return back.shown()

    def _mark(self, identifier: int, status: str) -> dict:
        idea = ideas.get(identifier)
        if idea.status == "ticket":
            raise ValueError("this idea is a ticket now — make it new again first")
        marked = ideas.decide(identifier, status)
        self._api.hub.publish("ideas", project=idea.project, **{status: identifier})
        return marked.shown()

    # -- writing by hand -------------------------------------------------------

    def create(self, payload: dict) -> dict:
        """An idea somebody wrote: its title, its description, its category, the project it is for."""
        project = ideas.bare(str(payload.get("project") or ""))
        if project and not any(
            ideas.bare(row["id"]) == project for row in self._api.all_projects()["projects"]
        ):
            raise LookupError(f"no project with id {project}")
        name, avatar = self.person()
        idea = ideas.written(
            project,
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            kind=str(payload.get("kind") or "ticket"),
            category=str(payload.get("category") or ""),
            author=name,
            avatar=avatar,
        )
        self._score_later(idea)
        self._api.hub.publish("ideas", project=project, written=idea.id)
        return ideas.get(idea.id).shown()

    def edit(self, identifier: int, payload: dict) -> dict:
        """Reword an idea, signed by whoever did."""
        name, avatar = self.person()
        idea = ideas.edit(
            identifier,
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            category=None if "category" not in payload else str(payload["category"] or ""),
            editor=name,
            avatar=avatar,
        )
        self._api.hub.publish("ideas", project=idea.project, edited=identifier)
        return idea.shown()

    def person(self) -> tuple[str, str]:
        """The name and the picture an idea written here is signed with."""
        with self._lock:
            if self._person is None:
                self._person = who()
            return self._person

    def write(
        self, project: str, kind: str, title: str, description: str = "", category: str = ""
    ) -> dict:
        """An idea an MCP client had, signed like one written in the console."""
        if kind not in ideas.KINDS:
            raise ValueError(f"an idea is a {' or a '.join(ideas.KINDS)} — not {kind}")
        if category and category not in ideas.CATEGORIES:
            raise ValueError(f"an idea is {', '.join(ideas.CATEGORIES)} — not {category}")
        if kind == "project" and ideas.scope_of(ideas.bare(project)) == "project":
            raise ValueError("an idea for a project is a ticket, never a project of its own")
        name, avatar = self.person()
        idea = ideas.written(
            project, title, description, kind=kind, category=category, author=name, avatar=avatar
        )
        self._score_later(idea)
        self._api.hub.publish("ideas", project=idea.project, written=idea.id)
        return ideas.get(idea.id).shown()

    def undo(self, project: str | None = None) -> dict:
        """Take the last decision back — in one scope, or the last of all when None.

        The idea is proposed again. What one turned into a ticket became stays
        on the board as a draft, and is said so: the board has no wastebasket the runner may
        reach into, and a ticket is not deleted on the strength of a swipe. It
        is what the idea becomes again if it is kept a second time.
        """
        last = ideas.last_decided(None if project is None else ideas.bare(project))
        if last is None:
            raise LookupError("no decision to take back")
        back = ideas.decide(last.id, "proposed")
        self._api.hub.publish("ideas", project=last.project, undone=last.id)
        return {"idea": back.shown(), "was": last.status}


def _by_scope(found: list[ideas.Idea]) -> dict[str, list[ideas.Idea]]:
    """Ideas grouped by the scope they are for, each one scored against its own."""
    groups: dict[str, list[ideas.Idea]] = {}
    for idea in found:
        groups.setdefault(idea.project, []).append(idea)
    return groups


def _readme(location: Path | None) -> str:
    if location is None:
        return ""
    for name in READMES:
        try:
            return (location / name).read_text(encoding="utf-8", errors="replace")[
                : ideas.README_LIMIT
            ]
        except OSError:
            continue
    return ""


def who() -> tuple[str, str]:
    """(name, picture) of the GitHub account `gh` speaks for, or git's `user.name`.

    ("", "") when neither says anything: the console then signs as "you".
    """
    try:
        answered = subprocess.run(
            ["gh", "api", "user"], capture_output=True, text=True, timeout=WHO_TIMEOUT
        )
        account = json.loads(answered.stdout) if answered.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        account = {}
    if isinstance(account, dict) and account.get("login"):
        name = str(account.get("name") or account["login"]).strip()
        return name, str(account.get("avatar_url") or "")
    try:
        answered = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, timeout=WHO_TIMEOUT
        )
        return answered.stdout.strip(), ""
    except (OSError, subprocess.SubprocessError):
        return "", ""
