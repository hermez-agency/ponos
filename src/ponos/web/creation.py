"""Creating a project from the console, and what is checked before the page exists.

A project used to be made in Notion and nowhere else, which was the one gesture
of the console's projects page that sent somebody away from it. It is made here
now — through the store, so a board of Markdown files gets its page the same
way — and what is refused is refused **before** anything is written, because a
page created and then found wrong is a page somebody has to go and delete.

Three refusals, each about one field, and said under that field (`Refused`
carries which): a name the workspace already has, whatever its case — two
projects nobody can tell apart in a menu are a ticket sent to the wrong one; a
repository that is not GitHub's, since GitHub is where the pull requests go;
and a folder that is not a git repository on this machine, which is what
`projects.Resolver` would refuse the first ticket over anyway.

What is written is what the projects database already says, column for column:
a database made by hand calls its repository "github" and its path "path", and
a page that invented "Repository" beside them would be a page whose repository
nobody sees. The columns this database does not have are left to the store —
Notion drops them, a file keeps them.

A repository nobody has cloned here is not refused: `projects.py` clones it at
the first ticket, and `check` says so while the form is being filled in.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import git, store
from .base import Base

# GitHub's own rules, near enough: an owner is letters, digits and inner
# hyphens; a repository adds dots and underscores.
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")
HOSTS = ("github.com", "www.github.com")

# The columns each value goes to, in the order `self.projects` reads them back.
# The first is the name a database of `ponos init`'s own makes.
COLUMNS = {
    "repository": ("Repository", "repository", "github", "repo"),
    "path": ("Path", "path"),
    "description": ("Description", "description"),
    "site": ("URL", "url", "Site", "site", "Website"),
}


class Refused(ValueError):
    """A project that will not be created, and the field that says why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def github_url(given: str) -> str:
    """`owner/name`, an https or ssh address, as `https://github.com/owner/name`.

    Empty when it is none of those: the caller says why, in its own words. A
    longer address — a branch, a file — is the repository it is in.
    """
    text = str(given or "").strip().rstrip("/")
    parts = git.reference_parts(text)
    if len(parts) >= 3 and parts[0].lower() in HOSTS:
        parts = parts[1:3]
    elif len(parts) != 2:
        return ""
    owner, name = parts[0], parts[1].removesuffix(".git")
    if not OWNER.fullmatch(owner) or not NAME.fullmatch(name) or name in (".", ".."):
        return ""
    return f"https://github.com/{owner}/{name}"


def is_site(given: str) -> bool:
    """Whether a site is an address a browser opens: http or https, a host, no space."""
    parsed = urlparse(given)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and " " not in given


def _column(schema: dict[str, str], used: dict[str, str], key: str) -> str:
    """The column that holds `key`: the one the pages fill in, the one the
    database declares, or the name `init` would give it — in that order.

    The pages first, because a board of Markdown files declares `init`'s names
    whatever its pages were written with.
    """
    names = COLUMNS[key]
    for known in (used, {name.lower(): name for name in schema}):
        found = next((known[name.lower()] for name in names if name.lower() in known), "")
        if found:
            return found
    return names[0]


class Creation(Base):
    def _say(self, key: str, **values: object) -> str:
        return self.runner.voice.say(key, **values)

    # -- what the form asks while it is filled in ---------------------------

    def check_project(self, repository: str = "", path: str = "") -> dict:
        """What a repository and a folder turn out to be, before anything is created.

        The repository, written the way it will be kept, and where this machine
        already has a clone of it — empty is "cloned at the first ticket". The
        folder, and the GitHub repository its `origin` names, for the form to
        fill in. A refusal is said as the creation would say it, not raised:
        the form asks this as somebody types.
        """
        answer: dict[str, Any] = {}
        if str(repository).strip():
            url = github_url(repository)
            if url:
                located = self.runner.resolver.locate("", "", url)
                answer.update(repository=url, cloned=str(located) if located else "")
            else:
                answer["repository_error"] = self._say(
                    "project-github-invalid", given=repository.strip()
                )
        if str(path).strip():
            try:
                folder = self._project_folder(path)
            except Refused as error:
                answer["path_error"] = str(error)
            else:
                origin = git.remote_url(folder)
                answer.update(path=str(folder), origin=github_url(origin) or origin)
        return answer

    def _project_folder(self, given: str) -> Path:
        """The folder a path names, refused unless it is a git repository here."""
        typed = str(given).strip()
        folder = Path(typed).expanduser()
        if not folder.is_absolute():
            raise Refused("path", self._say("project-path-relative"))
        if not folder.is_dir():
            raise Refused("path", self._say("project-path-missing", path=typed))
        if not git.is_repo(folder):
            raise Refused("path", self._say("project-path-not-git", path=typed))
        return folder

    # -- creating -----------------------------------------------------------

    def create_project(self, payload: dict[str, Any]) -> dict:
        """Create one project page, and hand it back as the list draws it."""
        database = self.runner.workspace.projects
        if not database:
            raise Refused("name", self._say("project-no-database"))
        name = " ".join(str(payload.get("name") or "").split())
        if not name:
            raise Refused("name", self._say("project-needs-name"))
        for row in self.all_projects()["projects"]:
            if row["name"].strip().casefold() == name.casefold():
                raise Refused("name", self._say("project-name-taken", name=row["name"]))

        repository = path = ""
        # A writing project has neither, whatever the form still held when
        # its type was changed: a page that names a repository is a code one.
        if payload.get("kind") != "document":
            given = str(payload.get("repository") or "").strip()
            if given:
                repository = github_url(given)
                if not repository:
                    raise Refused("repository", self._say("project-github-invalid", given=given))
            if str(payload.get("path") or "").strip():
                path = str(payload["path"]).strip().rstrip("/") or "/"
                folder = self._project_folder(path)
                # The page names its repository as well as its folder, so that
                # another machine — which has no such folder — finds it too.
                repository = repository or github_url(git.remote_url(folder))
            if not repository and not path:
                raise Refused("repository", self._say("project-needs-repository"))

        site = str(payload.get("site") or "").strip()
        if site and not is_site(site):
            raise Refused("site", self._say("project-site-invalid", given=site))

        client = self.runner.client
        schema = client.schema(database)
        used = {
            name.lower(): name
            for page in client.query(database)
            for name in page.properties
            if store.read(page, name) not in (None, "", [])
        }
        written = {
            _column(schema, used, key): value
            for key, value in (
                ("description", " ".join(str(payload.get("description") or "").split())),
                ("repository", repository),
                ("path", path),
                ("site", site),
            )
            if value
        }
        page_id = client.create_row(database, name, written)
        brief = str(payload.get("content") or "")
        if brief.strip():
            client.append_markdown(page_id, brief)

        page = client.page(page_id)
        bare = page_id.replace("-", "")
        # Read again next time, with this one in it — and every open console
        # told now rather than at the end of the index's ten minutes.
        self.forget_projects()
        self.hub.publish("projects", saved=bare)
        return {
            "id": bare,
            "name": name,
            "kind": "code" if (repository or path) else "document",
            "url": page.url,
            "repository": repository,
            "path": path,
            "description": written.get(_column(schema, used, "description"), ""),
            "site": site,
            **self._shown(bare),
            "configured": "",
            "source": "board",
        }
