"""Deleting a project from the console, and what that does and does not reach.

A project the console no longer shows is not enough: one that is only hidden is
still on the board, still synchronised, and its ready tickets are still taken by
the runner — which is what spends tokens. So deleting is done where the runner
looks: the project's page goes to the **Notion trash** (thirty days to bring it
back, and every query stops listing it), and what still points at it is dealt
with in the same gesture rather than at the next pass.

What is reached, and what never is, is the whole of the decision:

- **tickets** stay on the board by default, since they are somebody's work;
  those the runner could still pick up (ready, in progress) are put in
  *blocked* with a comment that says why. Trashing them too is an option the
  confirmation offers;
- **the GitHub repository, the clone on this machine and the branches** are not
  ours to remove, and are not touched. The throwaway worktrees under the state
  directory go — except one holding changes nobody committed;
- **the ideas** found for the project are dropped, with their cost. **History**
  (what was spent, how it ended) is kept as it is: the global statistics are a
  sum over it, and a deleted project's spending still happened;
- a **`[projects]` line** of the configuration naming it goes too, otherwise the
  project would come straight back as one "from the configuration".

A session running on one of its tickets refuses the deletion. Stopping a session
from here would be a second gesture hidden in the first one.
"""

from __future__ import annotations

from typing import Any

from .. import config as config_module
from .. import ideas, state, store
from ..ticket import short_id
from . import live
from .base import Base


class Removal(Base):
    def tickets_of(self, project: str) -> list[store.Page]:
        """The tickets whose project relation names that page."""
        settings = self.config.notion
        wanted = project.replace("-", "")
        pages = self.reader.read(self.runner.client, self.runner.database, settings.prop("status"))
        relation = settings.prop("project")
        return [
            page
            for page in pages
            if wanted in [str(one).replace("-", "") for one in store.read(page, relation) or []]
        ]

    def delete_project(self, page_id: str, payload: dict[str, Any]) -> dict:
        """Delete one project. Refuses, with its reason, before anything is changed."""
        bare = page_id.replace("-", "")
        row = next((one for one in self.projects().values() if one["id"] == bare), None)
        if row is None:
            raise LookupError(f"no project with id {bare}")
        name = row["name"]
        # The server asks for the name too: the typed confirmation is the
        # dialog's, but a gesture that can skip it is a gesture that will.
        if str(payload.get("confirm", "")).strip() != name:
            raise ValueError(f"type the project's name, “{name}”, to delete it")
        tickets = self.tickets_of(bare)
        shorts = {short_id(page.id) for page in tickets}
        running = [
            page
            for page in tickets
            if short_id(page.id) in {entry["source"] for entry in live.active()}
        ]
        if running:
            raise RuntimeError(
                f"a session is running on “{running[0].title or running[0].id}”, "
                f"a ticket of “{name}”: stop it or wait for it to end, then delete the project"
            )

        client = self.runner.client
        settings = self.config.notion
        blocked = settings.state("blocked")
        trash = bool(payload.get("trash_tickets"))
        said = self.runner.voice.say("project-deleted", project=name)
        stopped = trashed = 0
        # The tickets first: if the board refuses one, the project is still
        # there and the same request can be made again.
        for page in tickets:
            state.release(page.id)
            if trash:
                client.trash(page.id)
                self.reader.forget(page.id)
                trashed += 1
                continue
            if store.read(page, settings.prop("status")) in (
                settings.state("ready"),
                settings.state("running"),
            ):
                client.update(self.runner.database, page.id, {settings.prop("status"): blocked})
                client.comment(page.id, said)
                self.reader.hold(client.page(page.id))
                stopped += 1

        url = client.trash(bare)
        dropped = ideas.forget(bare)
        removed, kept = self.runner.drop_for(shorts)
        if name in self.config.projects:
            config_module.edit(self.config.path, [("projects", name, None)])
        # Shown gone at once: the index is read again, the tickets with it, and
        # every open console hears of it without waiting for the next poll.
        self.forget_projects()
        self.hub.publish("projects", deleted=bare)
        self.watch.nudge()
        return {
            "id": bare,
            "name": name,
            "url": url,
            "tickets": len(tickets),
            "blocked": stopped,
            "trashed": trashed,
            "ideas": dropped,
            "worktrees": len(removed),
            "kept": [path.name for path in kept],
        }
