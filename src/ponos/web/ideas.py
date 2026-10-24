"""Finding ideas from the console, and turning the kept ones into board pages.

`ideas.py` knows what an idea is and remembers it; this is the half that
reaches out — one session to propose a batch, the board to read what is
already there and to write a kept idea onto it. What it keeps is kept in
`base.py` with the rest of the console's state: the lock that keeps two
batches for the same scope from being asked for at once — the second click of
an impatient person would otherwise pay for ten ideas the first one was
already writing — and who signs an idea written here.

An idea turned into a ticket goes through `create_ticket`, the console's own "New ticket",
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
import logging
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from .. import goals, ideas, ids, log, provider, session, state, store
from ..config import state_dir
from .base import Base

logger = logging.getLogger(__name__)

# The README is read for what the project is; these are the names it goes by.
READMES = ("README.md", "README", "readme.md", "README.rst", "README.txt")

# How many decisions the history tab shows: enough to find the one you doubt.
HISTORY = 50

# `gh` asks GitHub, which is a request away: past this, the idea is signed as "you".
WHO_TIMEOUT = 5

# Language names as the prompt says them — see `voice.understood`.
LANGUAGES = {"en": "English", "fr": "French"}

# What `_ideas_busy` holds while ideas already there are being scored: no scope has
# this id, since a page id is hexadecimal.
SCORING = "scoring"


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="ponos-idea-scores", daemon=True).start()


class ScoreFailed(Exception):
    """A scoring call that gave no score, and the reason in a sentence — kept on the ideas it was for."""


class Ideas(Base):
    def ideas_later(self, work: Callable[[], None]) -> None:
        """How work that should not hold up an answer is run: in a thread of its
        own — and in place in a test, which replaces this to read what it wrote."""
        _thread(work)

    # -- reading --------------------------------------------------------------

    def proposed_ideas(self, project: str = "") -> dict:
        """The ideas still waiting for a decision in one scope, and what finding them cost."""
        project = ids.bare(project)
        batches, cost = ideas.spent(project)
        last = ideas.last_decided(project)
        return {
            "scope": ideas.scope_of(project),
            "project": project,
            "ideas": [idea.shown() for idea in ideas.listed(project)],
            "decided": [idea.shown() for idea in self._decided_ideas(project)],
            "batches": batches,
            "cost_usd": round(cost, 6),
            "undo": last.shown() if last else None,
        }

    def every_idea(self, project: str | None = "") -> dict:
        """Every idea of one scope, thrown away and turned into tickets included,
        and how many there are in each status — the list on a project's page.
        With None, those of every scope at once: the Ideas page's."""
        project = None if project is None else ids.bare(project)
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
    def _decided_ideas(project: str) -> list[ideas.Idea]:
        """The last ideas decided on, the most recent first: the history tab's."""
        decided = ideas.listed(project, ("kept", "discarded", "ticket"))
        decided.sort(key=lambda idea: (idea.decided_at or "", idea.id), reverse=True)
        return decided[:HISTORY]

    # -- finding --------------------------------------------------------------

    def generate_ideas(self, project: str = "", count: int | None = None) -> dict:
        """Ask for one batch, store what is new in it, and say what it cost.

        `count` ideas, `runner.ideas_per_batch` when the caller names no number.

        Raises RuntimeError when a batch for the same scope is already being
        written, and when the subscription is out of credit — the server's 409.
        """
        project = ids.bare(project)
        with self._ideas_lock:
            if project in self._ideas_busy:
                raise RuntimeError("ideas are already being found for this scope")
            self._ideas_busy.add(project)
        try:
            return self._generate_ideas(project, count)
        finally:
            with self._ideas_lock:
                self._ideas_busy.discard(project)

    def _idea_scope(
        self, project: str, *, readme: bool = True
    ) -> tuple[str, str, str, list[str], str]:
        """What a scope is: its name, its brief and its README for a project;
        the names of every project and the workspace's context for the workspace."""
        name, brief, text = "", "", ""
        names: list[str] = []
        context = ""
        if project:
            # The list's row rather than the board's: it carries the path the
            # configuration maps the project to, which is where its README is.
            row = next(
                (row for row in self.all_projects()["projects"] if row["id"] == project), None
            )
            if row is None:
                raise LookupError(f"no project with id {project}")
            name = row["name"]
            brief = self.runner.resolver.brief(self.runner.client, project)
            if readme:
                text = _readme(
                    self.runner.resolver.locate(
                        name,
                        row.get("configured") or row.get("path") or "",
                        row.get("repository") or "",
                    )
                )
        else:
            names = sorted((row["name"] for row in self.projects().values()), key=str.lower)
            try:
                context = self.runner.workspace.context
            except store.StoreError:
                context = ""
        return name, brief, text, names, context

    def _idea_objectives(self, project: str) -> list[goals.Goal]:
        """The goals being worked toward: the project's, or all of the workspace's."""
        runner = self.runner
        try:
            return goals.active(runner.client, runner.workspace.goals, project)
        except store.StoreError:
            return []

    def _generate_ideas(self, project: str, count: int | None = None) -> dict:
        configuration = self.config
        count = configuration.runner.ideas_per_batch if count is None else count
        name, brief, readme, names, context = self._idea_scope(project)
        tickets = self._idea_tickets(name if project else "")
        known = ideas.known(project)
        model = configuration.runner.allowed(configuration.runner.ideas_model)
        asked = ideas.prompt(
            project=name,
            brief=brief,
            readme=readme,
            tickets=tickets,
            projects=names,
            context=context,
            objectives=self._idea_objectives(project),
            known=known,
            language=LANGUAGES.get(self.runner.voice.language, "English"),
            count=count,
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
        batch, stored = ideas.record(project, model, outcome.cost_usd, kept[:count], error)
        self.hub.publish("ideas", project=project, batch=batch)
        return {
            "batch": batch,
            "ideas": [idea.shown() for idea in stored],
            "dropped": [candidate["title"] for candidate in dropped],
            "cost_usd": outcome.cost_usd,
            "model": model,
            "error": error,
        }

    def _idea_tickets(self, project: str) -> list[tuple[str, str]]:
        """The latest tickets of a project — of the board, for the workspace.

        Latest first, every column but the drafts and those nobody named: what
        has been done and what is being done is what an idea must not repeat.
        A board that cannot be read leaves the prompt without them, not the
        batch without its ideas.
        """
        try:
            tickets = self.board(max_age=self.config.web.poll_seconds)["tickets"]
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

    def unscored_ideas(self, project: str | None = None) -> dict:
        """How many ideas have no score yet, and what scoring them may cost at most.

        With None, those of every scope — the Ideas page's.
        """
        waiting = ideas.unscored(project)
        calls = sum(-(-len(group) // ideas.SCORE_BATCH) for group in _by_scope(waiting).values())
        configuration = self.config
        with self._ideas_lock:
            busy = SCORING in self._ideas_busy
        return {
            "count": len(waiting),
            "calls": calls,
            "ceiling_usd": round(calls * ideas.SCORE_CEILING_USD, 2),
            "model": configuration.runner.allowed(configuration.runner.classify_model),
            "running": busy,
        }

    def score_unscored_ideas(self, project: str | None = None) -> dict:
        """Score every idea that has none, behind the answer: say what was started.

        Raises RuntimeError when a pass is already scoring — the server's 409.
        """
        with self._ideas_lock:
            if SCORING in self._ideas_busy:
                raise RuntimeError("ideas are already being scored")
            self._ideas_busy.add(SCORING)

        def done() -> None:
            with self._ideas_lock:
                self._ideas_busy.discard(SCORING)

        try:
            waiting = ideas.unscored(project)
            for idea in waiting:
                ideas.scoring(idea.id)
            if waiting:
                self.hub.publish("ideas", project=project or "", scoring=len(waiting))
            started = self.unscored_ideas(project)
        except Exception:
            done()
            raise

        def work() -> None:
            failures: list[str] = []
            try:
                self.score_ideas([idea.id for idea in waiting], failures)
            finally:
                done()
                if failures:
                    self.hub.publish("ideas", project=project or "", failed=failures[0])

        self.ideas_later(work)
        return started

    def score_ideas(
        self, identifiers: list[int], failures: list[str] | None = None
    ) -> dict[int, int]:
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
                    scores = self._score_ideas(project, chunk)
                except ScoreFailed as failure:
                    scores, error = {}, str(failure)
                except Exception as failure:  # a score is never worth a crash
                    logger.exception("ideas: scoring failed", extra=log.FILE_ONLY)
                    scores, error = {}, f"{type(failure).__name__}: {failure}"
                if error:
                    logger.warning(
                        "ideas: scoring %d ideas of %s failed: %s",
                        len(chunk),
                        project or "the workspace",
                        error,
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
                self.hub.publish("ideas", project=project, scored=len(chunk))
        return found

    def _score_ideas(self, project: str, chunk: list[ideas.Idea]) -> dict[int, tuple[int, str]]:
        configuration = self.config
        name, brief, _, _, context = self._idea_scope(project, readme=False)
        asked = ideas.score_prompt(
            chunk,
            project=name,
            brief=brief,
            tickets=self._idea_tickets(name if project else ""),
            context=context,
            objectives=self._idea_objectives(project),
            known=ideas.known(project),
            language=LANGUAGES.get(self.runner.voice.language, "English"),
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

    def _score_idea_later(self, idea: ideas.Idea) -> None:
        """Score one idea written by hand, behind the answer that saved it."""
        ideas.scoring(idea.id)
        self.ideas_later(lambda: self.score_ideas([idea.id]))

    # -- deciding -------------------------------------------------------------

    def idea_ticket(self, identifier: int) -> dict:
        """Turn an idea into a draft ticket, or a new project and its first ticket.

        An idea turned into one before — and taken back since — already has its
        pages: they are what it becomes again, rather than a second copy of them.
        """
        idea = ideas.get(identifier)
        if idea.status == "ticket":
            return idea.shown()
        say = self.runner.voice.say
        created, ticket = idea.created, idea.ticket
        if idea.kind == "project":
            if not created:
                database = self.runner.workspace.projects
                if not database:
                    raise ValueError("this workspace has no projects database")
                created = ids.bare(self.runner.client.create_row(database, idea.title, {}))
                if idea.description.strip():
                    self.runner.client.append_markdown(created, idea.description.strip())
                self.forget_projects()
                self.hub.publish("projects", saved=created)
            if not ticket:
                ticket = self.create_ticket(
                    say("idea-frame", name=idea.title),
                    ideas.framing(idea, say),
                    project=created,
                    ready=False,
                )["id"]
        elif not ticket:
            ticket = self.create_ticket(
                idea.title, ideas.body(idea, say), project=idea.project, ready=False
            )["id"]
        made = ideas.decide(identifier, "ticket", ticket=ids.bare(ticket), created=created)
        self.hub.publish("ideas", project=idea.project, ticket=identifier)
        return made.shown()

    def keep_idea(self, identifier: int) -> dict:
        """Keep an idea for later: a decision, and nothing on the board yet."""
        return self._mark_idea(identifier, "kept")

    def discard_idea(self, identifier: int) -> dict:
        """Throw an idea away. Nothing else: it stays known, never to be proposed again."""
        return self._mark_idea(identifier, "discarded")

    def reopen_idea(self, identifier: int) -> dict:
        """Make an idea new again, whatever was decided about it.

        One that became a ticket leaves its ticket on the board, as `undo_idea` does.
        """
        idea = ideas.get(identifier)
        back = ideas.decide(identifier, "proposed")
        self.hub.publish("ideas", project=idea.project, reopened=identifier)
        return back.shown()

    def _mark_idea(self, identifier: int, status: str) -> dict:
        idea = ideas.get(identifier)
        if idea.status == "ticket":
            raise ValueError("this idea is a ticket now — make it new again first")
        marked = ideas.decide(identifier, status)
        self.hub.publish("ideas", project=idea.project, **{status: identifier})
        return marked.shown()

    # -- writing by hand -------------------------------------------------------

    def create_idea(self, payload: dict) -> dict:
        """An idea somebody wrote: its title, its description, its category, the project it is for."""
        project = ids.bare(str(payload.get("project") or ""))
        if project and not any(
            ids.bare(row["id"]) == project for row in self.all_projects()["projects"]
        ):
            raise LookupError(f"no project with id {project}")
        name, avatar = self.idea_person()
        idea = ideas.written(
            project,
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            kind=str(payload.get("kind") or "ticket"),
            category=str(payload.get("category") or ""),
            author=name,
            avatar=avatar,
        )
        self._score_idea_later(idea)
        self.hub.publish("ideas", project=project, written=idea.id)
        return ideas.get(idea.id).shown()

    def edit_idea(self, identifier: int, payload: dict) -> dict:
        """Reword an idea, signed by whoever did."""
        name, avatar = self.idea_person()
        idea = ideas.edit(
            identifier,
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            category=None if "category" not in payload else str(payload["category"] or ""),
            editor=name,
            avatar=avatar,
        )
        self.hub.publish("ideas", project=idea.project, edited=identifier)
        return idea.shown()

    def idea_person(self) -> tuple[str, str]:
        """The name and the picture an idea written here is signed with."""
        with self._ideas_lock:
            if self._ideas_person is None:
                self._ideas_person = who()
            return self._ideas_person

    def write_idea(
        self, project: str, kind: str, title: str, description: str = "", category: str = ""
    ) -> dict:
        """An idea an MCP client had, signed like one written in the console."""
        if kind not in ideas.KINDS:
            raise ValueError(f"an idea is a {' or a '.join(ideas.KINDS)} — not {kind}")
        if category and category not in ideas.CATEGORIES:
            raise ValueError(f"an idea is {', '.join(ideas.CATEGORIES)} — not {category}")
        if kind == "project" and ideas.scope_of(ids.bare(project)) == "project":
            raise ValueError("an idea for a project is a ticket, never a project of its own")
        name, avatar = self.idea_person()
        idea = ideas.written(
            project, title, description, kind=kind, category=category, author=name, avatar=avatar
        )
        self._score_idea_later(idea)
        self.hub.publish("ideas", project=idea.project, written=idea.id)
        return ideas.get(idea.id).shown()

    def undo_idea(self, project: str | None = None) -> dict:
        """Take the last decision back — in one scope, or the last of all when None.

        The idea is proposed again. What one turned into a ticket became stays
        on the board as a draft, and is said so: the board has no wastebasket the runner may
        reach into, and a ticket is not deleted on the strength of a swipe. It
        is what the idea becomes again if it is kept a second time.
        """
        last = ideas.last_decided(None if project is None else ids.bare(project))
        if last is None:
            raise LookupError("no decision to take back")
        back = ideas.decide(last.id, "proposed")
        self.hub.publish("ideas", project=last.project, undone=last.id)
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
