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
edited — see `Tickets._brief`.

Which is why the console is *one* object, for as long as it serves, as a run
is: every one of those reads is kept once, and so are the moves waiting for
Notion and the stream every open page listens to. A second holder of any of
them is a page told one thing by the stream and another by the board — a
project renamed in one pane and not in the next, a move sent twice. So the
state is not split: `base.py` holds it, and says what each piece is.

What was split is the work, the way the runner's `base.py` splits a run's.
Each thing the console is asked about — the board and its tickets, the
projects, creating one and deleting one, the goals, the schedules, the
settings, what the header and the statistics say, the health of the
installation and its tidying, the journals, the discussion on a ticket and
the decisions it waits on, the ideas — is a class of its own in a module of
its own, and `Api` is those classes put together over `Base`. Classes that
*add methods* to the one object, rather than collaborators holding a
reference back to it: the console had both, and the second kind is what this
shape replaced. `creation.py`, `removal.py` and `ideas.py` were each an object
handed the `Api` it served — three modules importing back the class that
imported them, `self._api.` in front of every call, and the ideas' lock kept
apart from the rest of the state. Assembled, a route asks
`api.create_project(...)` the way it asks `api.board()`, a chapter calls
another as `self.projects()`, and each module reads as the chapter it is —
which a single class of two thousand lines, the other way of keeping one
object, never did.

The price is the runner's too: read alone, a chapter has no `board` — `Tickets`
brings it. `base.Chapters` tells the type checker what crosses from one chapter
to another. No two chapters define the same name, so the order below says
nothing; what is left in this module is the assembly, and nothing else.
"""

from __future__ import annotations

from . import (
    base,
    configuration,
    creation,
    discussion,
    goals,
    ideas,
    journals,
    overview,
    projects,
    removal,
    schedules,
    tickets,
    upkeep,
)


class Api(
    tickets.Tickets,
    projects.Projects,
    creation.Creation,
    removal.Removal,
    goals.Goals,
    schedules.Schedules,
    configuration.Configuration,
    overview.Overview,
    upkeep.Upkeep,
    journals.Journals,
    discussion.Discussion,
    ideas.Ideas,
    base.Base,
):
    """The console, over everything it is asked about."""
