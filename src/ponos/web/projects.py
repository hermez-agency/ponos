"""The projects: their index, their pages, their pictures.

A project is a page of the projects database, written by hand, so it is read
the way a hand writes it — "Repository", "repository", or the bare "github" —
and written back under the name the page already carries. The index of them is
one query kept for a few minutes, because the board names a project on every
card and asks at every reading; creating one is `creation.py`'s, deleting one
`removal.py`'s, and what a project decides for itself is `configuration.py`'s.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from .. import store
from .base import Base
from .creation import COLUMNS, is_site

# The project index is read from one database query, not one page fetch per
# project — and kept, because projects are renamed about as often as they are
# created. Ten minutes is short enough that a new project appears on its own.
PROJECT_TTL = 600


class Projects(Base):
    def projects(self) -> dict[str, dict[str, Any]]:
        """{page id: {name, kind, …}} — one query, kept for a few minutes.

        Read from the projects database in one go rather than resolved ticket by
        ticket: resolving costs two API calls per project, and the board asks
        this question every time it refreshes.
        """
        if self._projects and time.time() - self._projects_at < PROJECT_TTL:
            return self._projects
        index: dict[str, dict[str, Any]] = {}
        try:
            database = self.runner.workspace.projects
            if database:
                for page in self.runner.client.query(database):
                    repository = _first(page, "Repository", "repository", "github", "repo")
                    path = _first(page, "Path", "path")
                    index[page.id] = {
                        "id": page.id.replace("-", ""),
                        "name": page.title or "(untitled project)",
                        "kind": "code" if (repository or path) else "document",
                        "url": page.url,
                        "repository": repository,
                        "path": path,
                        "description": _first(page, *COLUMNS["description"]),
                        "site": _first(page, *COLUMNS["site"]),
                        **self._pictures(page),
                    }
        except store.StoreError:
            # A projects database that cannot be read costs the board its
            # project names, and nothing else. The tickets still show.
            return self._projects
        self._projects = index
        self._projects_at = time.time()
        return index

    def _pictures(self, page: store.Page) -> dict[str, dict[str, Any]]:
        """A project's cover and icon, read with the rest of the page.

        Reading the projects database is the synchronisation: what somebody
        changed in Notion is agreed on here, and a change of the console's that
        Notion refused last time is sent again. A cache that cannot be written
        costs the pictures, never the list.
        """
        client = self.runner.client
        try:
            self.images.observe(
                page, lambda slot, picture: client.set_picture(page.id, slot, picture)
            )
        except OSError:
            pass
        return self._shown(page.id)

    def _shown(self, page_id: str) -> dict[str, dict[str, Any]]:
        """Both pictures of a page, each at the console's own address for it."""
        bare = page_id.replace("-", "")
        shown: dict[str, dict[str, Any]] = {}
        for slot in store.SLOTS:
            said = self.images.shown(bare, slot)
            version = said.pop("version", "")
            if said["kind"] == "image":
                said["src"] = f"/api/projects/{bare}/image/{slot}?v={version}"
            shown[slot] = said
        return shown

    def all_projects(self) -> dict[str, Any]:
        """Every project this installation knows of, from wherever it knows it.

        Three sources, and the pane shows the three as one list because that is
        how somebody thinks of their projects: the board's own database; the
        `[projects]` table of the configuration, which is a path this machine
        maps a name onto; and — for either of those — where the repository
        actually turned out to be on this disk.

        A configuration entry for a project the board already has is not a
        second project: it is the same one, with its path resolved. Only a name
        the board has never heard of adds a row, and it is marked as coming from
        the file so that nobody goes looking for its page.
        """
        rows: list[dict[str, Any]] = []
        try:
            known = self.projects()
        except store.StoreError:
            known = {}
        overrides = dict(self.config.projects)
        for project in sorted(known.values(), key=lambda item: item["name"].lower()):
            declared = overrides.pop(project["name"], "")
            rows.append({**project, "configured": declared, "source": "board"})
        for name, path in sorted(overrides.items(), key=lambda pair: pair[0].lower()):
            rows.append(
                {
                    "id": "",
                    "name": name,
                    "kind": "code",
                    "url": "",
                    "repository": "",
                    "path": path,
                    "configured": path,
                    "source": "config",
                }
            )
        # No count of tickets per project: that was the whole tickets database
        # read again on every call, three hundred pages to write six numbers,
        # while the console already holds every ticket the stream sent it. It
        # counts them there.
        return {
            "projects": rows,
            "workspace_root": str(self.config.runner.workspace_root),
            "storage": self.config.storage.mode,
        }

    def project(self, page_id: str) -> dict[str, Any]:
        """One project, as the list says it, plus what is written on its page.

        The row is `all_projects`' own, so a project opened reads like the
        project listed — and what a card cannot carry is added here: the brief.
        Which is the reason a project is worth opening at all. It is not
        decoration on the page, it is standing instructions: the audience, the
        voice, the conventions, the things never to do. `projects.brief` reads
        the same text into every ticket of that project.
        """
        wanted = page_id.replace("-", "")
        row = next((item for item in self.all_projects()["projects"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no project with id {wanted}")
        # Where the clone really is, which neither declaration says when the
        # repository was found by its remote. Left out of the list: finding it
        # walks the disk, and a card has no room for it.
        located = self.runner.resolver.locate(
            row["name"], row.get("configured") or row.get("path") or "", row.get("repository") or ""
        )
        content = self.runner.client.blocks_text(page_id)
        return {
            **row,
            "located": str(located) if located else "",
            "content": content,
            "version": _digest(content),
        }

    def project_brief(self, page_id: str) -> dict[str, Any]:
        """The brief as the editor opens it: the text, its version, what saving it would lose.

        Read when somebody starts editing rather than with the page, because
        that is the moment the two other answers are measured from. `version`
        is what `save_project` is handed back as `base`: a brief that no longer
        says that has been written to since, and is not overwritten. `losses` is
        what the Markdown cannot hold of the page as it is now — see
        `markdown.lost` — kind by kind, for the editor to say before it saves.
        """
        client = self.runner.client
        content = client.blocks_text(page_id)
        return {
            "content": content,
            "version": _digest(content),
            "losses": client.losses(page_id),
        }

    def save_project(self, page_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Change one project page from the console.

        What a project is: its name, what it does in a sentence, its public
        address, the repository its tickets are worked in, the path this
        machine finds that repository at, and the brief. Never its tickets —
        those point at the page, and are moved on the board.

        Its type is no column: a page that names a repository or a folder is a
        code project (see `projects`). So "document" empties both, and "code"
        is refused when neither would be left — a type corrected after the
        creation is a type that holds, not one the next reading undoes.

        The columns are written under the name the page already carries:
        a project database is written by hand, so "Repository" is sometimes
        "github" and sometimes "repo", and a save that invented a second column
        beside the one somebody filled in would be a save that changes nothing
        anybody can see. `projects.py` reads them the same way.
        """
        database = self.runner.workspace.projects
        if not database:
            raise ValueError("this workspace has no projects database")
        page = self.runner.client.page(page_id)
        written: dict[str, Any] = {}
        if "repository" in values:
            column = _column(page, "Repository", "repository", "github", "repo")
            written[column] = str(values["repository"] or "")
        if "path" in values:
            written[_column(page, "Path", "path")] = str(values["path"] or "")
        if values.get("kind") == "document":
            written[_column(page, *COLUMNS["repository"])] = ""
            written[_column(page, *COLUMNS["path"])] = ""
        elif values.get("kind") == "code":
            kept = {
                key: str(values[key] or "").strip()
                if key in values
                else _first(page, *COLUMNS[key])
                for key in ("repository", "path")
            }
            if not any(kept.values()):
                raise ValueError(self.runner.voice.say("project-needs-repository"))
        if "description" in values:
            description = " ".join(str(values["description"] or "").split())
            written[_column(page, *COLUMNS["description"])] = description
        if "site" in values:
            site = str(values["site"] or "").strip()
            if site and not is_site(site):
                raise ValueError(self.runner.voice.say("project-site-invalid", given=site))
            written[_column(page, *COLUMNS["site"])] = site
        if str(values.get("name", "")).strip():
            written[self.runner.client.title_property(database)] = str(values["name"]).strip()
        if not written and "content" not in values:
            raise ValueError("nothing to change")
        if "content" in values:
            self._guard_brief(page_id, values)
        if written:
            self.runner.client.update(database, page_id, written)
        # Replacing, not appending: the brief is a value. See `save_context`,
        # which is the same gesture on the one page above all projects.
        if "content" in values:
            self.runner.client.replace_markdown(page_id, str(values["content"]))
        # The index is kept for ten minutes, and a rename that took that long to
        # show would be a rename somebody made twice.
        self._projects = {}
        self._projects_at = 0.0
        self.hub.publish("projects", saved=page_id)
        return self.project(page_id)

    def _guard_brief(self, page_id: str, values: dict[str, Any]) -> None:
        """Refuse a brief that would overwrite what it was not written from.

        Two refusals, both only asked for by a caller that says what it saw. A
        `base` — the `version` it opened the brief at — that the page no longer
        has is a conflict (409: somebody wrote to it in Notion meanwhile). And
        a page that holds what Markdown cannot is rewritten only once the caller
        says it knows (`accept_losses`), so that nothing a page holds goes
        without having been shown. A caller that sends neither, like the edit
        form, keeps the plain replacement it always had.
        """
        client = self.runner.client
        if "base" in values and _digest(client.blocks_text(page_id)) != values["base"]:
            raise RuntimeError("this brief changed in the board since it was opened")
        if "base" in values and not values.get("accept_losses"):
            if client.losses(page_id):
                raise ValueError(
                    "this brief holds what Markdown cannot keep; saving it would lose it"
                )

    def set_picture(self, page_id: str, slot: str, picture: store.Picture) -> dict[str, Any]:
        """Change a project's cover or icon, and say where that leaves it.

        Shown here at once, whatever the board says: what it refused stays
        pending, with the reason, and is sent again at the next reading of the
        projects. Which is why the answer is the two pictures and not the whole
        project — rereading the page is exactly what a board that is not
        answering would refuse too.
        """
        if slot not in store.SLOTS:
            raise ValueError(f"a project has a cover and an icon, not a {slot}")
        if not self.runner.workspace.projects:
            raise ValueError("this workspace has no projects database")
        bare = page_id.replace("-", "")
        client = self.runner.client
        self.images.change(
            bare, slot, picture, lambda which, chosen: client.set_picture(bare, which, chosen)
        )
        shown = self._shown(bare)
        for row in self._projects.values():
            if row["id"] == bare:
                row.update(shown)
        self.hub.publish("projects", saved=bare)
        return {"id": bare, **shown}

    def picture(self, page_id: str, slot: str) -> tuple[bytes, str]:
        """The bytes of a project's picture, from this machine's copy.

        Never a redirect to where the board keeps it: a Notion file's URL is
        good for an hour, and a console left open is open longer than that.
        """
        if slot not in store.SLOTS:
            raise LookupError(f"a project has a cover and an icon, not a {slot}")
        return self.images.picture(page_id, slot, lambda: self.runner.client.page(page_id))


def _first(page: store.Page, *names: str) -> str:
    """The first of those columns the page actually carries, as text.

    A project database is written by hand, so its columns are named by hand:
    "Repository", "repository", or the bare "github" the runner used to ask for.
    `projects.py` reads them the same way, for the same reason.
    """
    for name in names:
        value = store.read(page, name)
        if value not in (None, "", []):
            return str(value)
    return ""


def _relation(page: store.Page, *names: str) -> list[str]:
    """The page ids of the first of those relations the page carries."""
    for name in names:
        value = store.read(page, name)
        if isinstance(value, list) and value:
            return [str(one) for one in value if one]
    return []


def _column(page: store.Page, *names: str) -> str:
    """The first of those columns the page actually carries, by name.

    What `_first` reads, written back: a value goes to the column somebody
    filled in rather than to a second one beside it. A page carrying none of
    them is written under the first name, which is the one this project would
    have been given had it been created here.
    """
    lookup = {key.lower(): key for key in page.properties}
    for name in names:
        found = lookup.get(name.lower())
        if found is not None:
            return found
    return names[0]


def _digest(text: str) -> str:
    """A short name for a text, to tell whether it is still the one that was read."""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]
