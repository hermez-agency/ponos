"""What the runner needs from the board: its collections, and the standing context.

`ponos.db` holds five collections — tickets, projects, agents, schedules,
goals — and one page that belongs to none of them, the context every ticket
starts from. Only the tickets are required: a board without a context runs
exactly as before, and the runner says so and carries on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import BoardNames
from .store import Store


@dataclass
class Workspace:
    tickets: str = ""
    projects: str = ""
    agents: str = ""
    # What comes back on its own. Absent means nothing repeats here, which is
    # not a fault: the collection is optional exactly as the other two are.
    schedules: str = ""
    # What a ticket is for — see goals.py. Absent is said, never failed: a
    # ticket without its goal still runs, it just does not know why.
    goals: str = ""
    context: str = ""
    # The page the context was read off, so that it can be written back: the
    # console edits it as a text area, and a text you can read but not save is
    # worse than one you cannot see. Empty where there is no such page.
    context_page: str = ""
    rows: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def resolve(backend: Store, settings: BoardNames) -> Workspace:
    """The collections and the standing context, as the board says them."""
    return backend.workspace(settings)
