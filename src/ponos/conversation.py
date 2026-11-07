"""Talking to the runner in the comments, rather than only through the board.

A ticket already had one way of answering you: it ran. You wrote a comment
under a `blocked` report, the next run read it and did the work again. That is
the right gesture for *do this differently* — and the wrong one for *why did you
do it like that?*, which is most of what one actually wants to say to something
that just wrote code on one's behalf.

So a comment can also simply be **answered**. Same place, same thread, no status
moved, nothing built: the runner replies under your question the way a colleague
would, and the board does not pretend anything happened.

Three rules keep that from turning into noise, and they are all about knowing
who is being spoken to:

- **a thread the runner already speaks in belongs to it.** Reply under its
  report and it answers you. A new remark elsewhere on the page is a
  conversation of yours, and stays one;
- **naming it works wherever the runner is looking.** A comment carrying
  `@claude`, `@ponos` or `@runner` — is addressed to the runner,
  whatever the ticket's status. Where it looks is `Threads`' business;
- **work wins over talk.** A plain answer under a question a run asked is still
  what puts the ticket back in the queue: that loop was the point of `blocked`,
  and it keeps it. Naming the runner is how you ask for words instead.

And one rule about not talking to itself. Every comment the runner writes comes
back to it on the next pass; recognising its own voice by the signature it
happens to write would hold until the day it writes something else. So it asks
the board for its own identity and compares it with the comment's author — and
when it cannot get one, it says nothing at all. A conversation with oneself is the single failure
mode here that never ends on its own.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import db, store, voice
from .config import state_dir

# What to call it when you want its attention: a word you would type.
MENTION = "@claude"

# Always understood too: the tool's own name is not something anyone should
# have to declare in order to be able to use it.
ALIASES = ("@ponos", "@runner")

# How many answers one pass writes: they are Claude sessions, and five people
# waiting is already a busy afternoon.
ANSWERS = 5

# How a comment relayed from Telegram or Slack opens (see `channels.answer`).
# It is written by the integration and it is *not* the runner speaking: it is
# you, from your phone, and it has to wake a blocked ticket exactly as the same
# words typed into the console would. Shared with `channels` rather than spelled
# twice, because the day the sentence changes in one place and not the other,
# every answer given from a phone stops arriving. Every language's opening, not
# only the configured one: the answers given before `runner.language` changed
# are still on the board, and still yours.
RELAYED = voice.openings("relayed")

# A comment is a comment. Past this, the answer is a document, and a document
# belongs in the page rather than under it.
ANSWER_CHARS = 4000

# How many of the tickets most recently commented on a pass reads. Beyond this a
# conversation nobody has touched in two hundred tickets is over.
REMEMBERED = 200


@dataclass
class Thread:
    """One discussion on a page, oldest comment first.

    Comments are grouped into discussions, and that grouping is what makes an
    answer an answer: posted into the thread it belongs to, it sits under the
    question instead of at the bottom of the page.
    """

    discussion: str
    comments: list[store.Comment] = field(default_factory=list)

    @property
    def last(self) -> store.Comment:
        return self.comments[-1]

    def spoken_by(self, user: str) -> bool:
        return any(ours(comment, user) for comment in self.comments)


def is_relayed(text: str) -> bool:
    """Was this comment written by the integration on somebody else's behalf?

    An answer given in Telegram or Slack is posted here by the runner's own
    token, which makes it look like the runner talking. It is not: it is the
    ticket's author, one device removed.
    """
    return text.lstrip().startswith(RELAYED)


def said(text: str) -> str:
    """A relayed comment without the line that says where it came from.

    “Answered from Telegram by Alice.” is an address, not a message: read back
    in the console's own terminal the words belong under your name, and the name
    is already on the turn.
    """
    text = text.strip()
    if not is_relayed(text):
        return text
    _, _, rest = text.partition("\n")
    return rest.strip() or text


def ours(comment: store.Comment, me: str) -> bool:
    """Is this the runner's own voice — not merely its token?"""
    return bool(me) and comment.created_by == me and not is_relayed(comment.text)


def threads(comments: Iterable[store.Comment]) -> list[Thread]:
    """The comments of a page, grouped into their discussions, in order.

    A comment that names no discussion is a thread of one rather
    than a thread of everything: lumping unrelated remarks together would have
    the runner answer a question nobody asked it.
    """
    order: list[str] = []
    grouped: dict[str, Thread] = {}
    for index, comment in enumerate(comments):
        key = comment.discussion_id or comment.id or f"loose-{index}"
        if key not in grouped:
            grouped[key] = Thread(key)
            order.append(key)
        grouped[key].comments.append(comment)
    return [grouped[key] for key in order]


def names(mention: str = "", integration: str = "") -> tuple[str, ...]:
    """Every way of naming the runner in a comment.

    The word, the built-in aliases, and the board's own name for the runner
    — the last one because @-mentioning it is the gesture people actually
    make. A name under four characters is left out: a bot called “IA” would
    answer every sentence containing it.
    """
    found = [mention.strip() or MENTION, *ALIASES]
    if len(integration.strip()) >= 4:
        found.append(integration.strip())
    return tuple(dict.fromkeys(name for name in found if name))


def addressed(text: str, spellings: Iterable[str]) -> bool:
    """Is this comment speaking *to* the runner, rather than about the ticket?

    Matched as a whole word, with or without its `@`, anywhere in the comment —
    “@claude tu peux relire ?” and “une idée, claude ?” are the same gesture.
    Inside a longer word it is not: `claudette` is somebody's name.
    """
    for spelling in spellings:
        bare = re.escape(spelling.lstrip("@"))
        if re.search(rf"(?<![\w@])@?{bare}\b", text, flags=re.IGNORECASE):
            return True
    return False


def waiting(
    comments: Iterable[store.Comment], *, me: str, spellings: Iterable[str]
) -> list[Thread]:
    """The threads of a page that are waiting on a reply from the runner.

    Empty when we do not know who we are: without an identity there is no way to
    tell our own last word from yours, and answering ourselves is worse than
    answering nothing.
    """
    if not me:
        return []
    pending = []
    for thread in threads(comments):
        last = thread.last
        if not last.text.strip() or ours(last, me):
            continue
        if addressed(last.text, spellings) or thread.spoken_by(me):
            pending.append(thread)
    return pending


def strip_mention(text: str, spellings: Iterable[str]) -> str:
    """The message without the name it opens with.

    Only at the start, and only once: “@claude pourquoi ?” is addressed to the
    runner and says “pourquoi ?”, while a name in the middle of a sentence is
    part of the sentence.
    """
    for spelling in spellings:
        bare = re.escape(spelling.lstrip("@"))
        cleaned = re.sub(rf"^\s*@?{bare}\b[\s,:—-]*", "", text, count=1, flags=re.IGNORECASE)
        if cleaned != text:
            return cleaned.strip() or text.strip()
    return text.strip()


def transcript(thread: Thread, me: str, limit: int = 12, budget: int = 2000) -> list[str]:
    """What has been said in this thread, ready for a prompt, newest last.

    Bounded like the ticket's own discussion is, and for the same reason: a
    thread six answers deep would otherwise spend the prompt on itself. The
    last comment is left out — it is the message being answered, and it gets a
    section of its own.
    """
    lines: list[str] = []
    for comment in reversed(thread.comments[:-1][-limit:]):
        who = "you" if ours(comment, me) else "them"
        line = f"{who}: {' '.join(comment.text.split())}"
        budget -= len(line)
        if budget < 0:
            break
        lines.append(line)
    return list(reversed(lines))


# -- what the runner remembers between passes --------------------------------


@dataclass
class Threads:
    """Where a conversation may be waiting, and the session that is having it.

    Both are read off the board's own comments, in `ponos.db`. **Where to look**
    is the tickets most recently commented on — a read of the file, not a
    request per page, so there is no window to move and no interval to wait
    out. **The session** is kept on the runner's answer itself, in the column
    `session` of its comment, so a follow-up question lands in the same Claude
    session as the one before it and the conversation is a conversation rather
    than a series of strangers. `database` names another file, for a test.
    """

    database: Path | None = None

    def recent(self) -> list[str]:
        """The tickets commented on most recently first, `REMEMBERED` at most."""
        try:
            with db.transaction(immediate=False, location=self.database) as connection:
                rows = connection.execute(
                    "SELECT ticket FROM ticket_comments GROUP BY ticket "
                    "ORDER BY MAX(id) DESC LIMIT ?",
                    (REMEMBERED,),
                ).fetchall()
        except db.ERRORS:
            return []
        return [str(ticket) for (ticket,) in rows]

    def last(self) -> int:
        """The newest comment on the board, by its number: 0 when there is none."""
        try:
            with db.transaction(immediate=False, location=self.database) as connection:
                row = connection.execute("SELECT MAX(id) FROM ticket_comments").fetchone()
        except db.ERRORS:
            return 0
        return int(row[0] or 0) if row else 0

    def session_of(self, ticket: str, discussion: str) -> str:
        """The session that last answered in that thread, or ""."""
        try:
            with db.transaction(immediate=False, location=self.database) as connection:
                row = connection.execute(
                    "SELECT session FROM ticket_comments WHERE ticket = ? AND discussion = ? "
                    "AND session != '' ORDER BY id DESC LIMIT 1",
                    (_key(ticket), discussion),
                ).fetchone()
        except db.ERRORS:
            return ""
        return str(row[0]) if row else ""

    def remember(self, ticket: str, discussion: str, session: str) -> None:
        """The answer just written in that thread was this session's.

        Best effort: a session not written down costs the next question a fresh
        session, never an answer.
        """
        try:
            with db.transaction(location=self.database) as connection:
                connection.execute(
                    "UPDATE ticket_comments SET session = ? WHERE id = "
                    "(SELECT MAX(id) FROM ticket_comments WHERE ticket = ? AND discussion = ?)",
                    (session, _key(ticket), discussion),
                )
        except db.ERRORS:
            pass

    def forget(self, ticket: str, discussion: str) -> None:
        """A session that could not be resumed is a session that is gone.

        Its transcript was pruned, or the machine changed. The thread keeps its
        history on the board, which is enough to start a fresh one from.
        """
        try:
            with db.transaction(location=self.database) as connection:
                connection.execute(
                    "UPDATE ticket_comments SET session = '' WHERE ticket = ? AND discussion = ?",
                    (_key(ticket), discussion),
                )
        except db.ERRORS:
            pass

    def talked_on(self) -> set[str]:
        """The tickets a session still answers on — their scratch directories are kept."""
        try:
            with db.transaction(immediate=False, location=self.database) as connection:
                rows = connection.execute(
                    "SELECT DISTINCT ticket FROM ticket_comments WHERE session != ''"
                ).fetchall()
        except db.ERRORS:
            return set()
        return {str(ticket) for (ticket,) in rows}


def _key(ticket: str) -> str:
    return ticket.replace("-", "")


def trim(answer: str, limit: int = ANSWER_CHARS) -> str:
    """An answer cut to the length of a comment, on a paragraph if it can be."""
    answer = answer.strip()
    if len(answer) <= limit:
        return answer
    cut = answer[:limit]
    edge = max(cut.rfind("\n\n"), cut.rfind("\n"), cut.rfind(". "))
    if edge > limit // 2:
        cut = cut[: edge + 1]
    return cut.rstrip() + "\n\n[…] the rest was too long for a comment — ask for it in pieces."


def talk_dir(short: str) -> Path:
    """Where a conversation about a ticket without a repository runs.

    Kept rather than made and destroyed, because Claude Code files a session
    under the directory it ran in: a scratch directory drawn afresh every time
    would make every follow-up a stranger.
    """
    path = state_dir() / "talks" / short
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_talks(keep: Iterable[str]) -> int:
    """Drop the scratch directories of conversations no longer remembered."""
    root = state_dir() / "talks"
    if not root.is_dir():
        return 0
    wanted = set(keep)
    removed = 0
    for path in root.iterdir():
        if path.name not in wanted and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
