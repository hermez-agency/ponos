"""Talking: the discussion on a ticket, the decisions a card waits on, and the chat's frame.

Nothing here is a new place to talk. A ticket's discussion is the one Notion
already holds, read as a conversation and answered in the thread the runner
last spoke in; a decision is a comment on that same thread and, when the ticket
goes back to work, a move. What is said from the console says it was relayed,
because the only token the console has is the runner's: without that line the
next run would read its own voice, and answer itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .. import channels, conversation, decisions, git, question, redaction, store, voice
from .. import goals as goals_module
from . import board as board_module
from .base import Base
from .tickets import _columns, _status


class Discussion(Base):
    def talk(self, page_id: str) -> dict[str, Any]:
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

    def tell(self, page_id: str, text: str) -> dict[str, Any]:
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

    def decision(self, page_id: str) -> dict[str, Any]:
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
        stopped = decisions.blockage(comment.text for comment in comments)
        solutions = decisions.unblocking(stopped, models=self._has("model"), cancel=self._cancels())
        asked = stopped.question
        return {
            "id": page.id.replace("-", ""),
            "column": column,
            "category": stopped.category,
            "declared": stopped.declared,
            "reported": stopped.reported,
            "reason": stopped.reason,
            "done": stopped.done,
            "detail": stopped.detail,
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
    ) -> dict[str, Any]:
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
            # The parts serve what the whole served: without its goal, a ticket
            # split in two would leave the goal's count behind.
            goal = goals_module.pointed(page, settings.prop("goal"))
            told = said.say("told-split", title=page.title, url=page.url)
            created = [
                self.create_ticket(
                    title, told, relation[0] if relation else "", ready=False, goal=goal
                )
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

    def _offered(self, solutions: list[decisions.Solution]) -> list[dict[str, Any]]:
        said = self.runner.voice
        return [
            {**solution.as_dict(), "label": decisions.label(said, solution)}
            for solution in solutions
        ]

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
