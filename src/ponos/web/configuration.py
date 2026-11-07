"""What the console lets you set: the file, a project's own settings, the standing context.

Three things written in three places — `config.toml`, `ponos.db` and a page of
the board — and one chapter for them, because to whoever opens the settings
they are one question: what will the runner do, and where is that decided.
Every save here drops what was read under the old answer, since a token, a
workspace or a property name changed is a different board.
"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from typing import Any

from .. import (
    browser,
    diagnostic,
    idea_schedule,
    library,
    local_ci,
    memory,
    notes,
    planning,
    preview,
    project_settings,
    skills,
    store,
    subtypes,
    vault,
    vault_store,
)
from .. import config as config_module
from .. import kinds as kinds_module
from . import settings as settings_module
from .base import Base


class Configuration(Base):
    # -- the configuration ----------------------------------------------------

    def settings(self) -> dict[str, Any]:
        """Every setting the file holds, as the console draws it — secrets aside.

        And the projects that decide their automatic validation for themselves,
        which the file does not hold but its validation card has to say: a
        switch that reads "on" is not the whole truth on those.
        """
        return {
            **settings_module.describe(self.config),
            "own_validation": project_settings.owning_validation(),
        }

    def folder(self, typed: str) -> dict[str, Any]:
        """A folder of this machine, for a path field to pick a file or a folder from."""
        return settings_module.folder(typed)

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write what the console changed, and pick the new file up at once.

        The caches go first because a saved token, workspace or property name is
        a different board: keeping the old client would have the console explain
        that the setting did not work.
        """
        result = settings_module.save(self.config, payload)
        if result["saved"]:
            self.forget()
            self.hub.publish("settings", saved=result["saved"])
            self.watch.nudge()
        return result

    # -- a project's own settings ---------------------------------------------

    def _validation_fields(self) -> list[dict[str, Any]]:
        """The global card's switches, as they are worded there — one source for both pages."""
        section = next(item for item in settings_module.SECTIONS if item.key == "validation")
        return [
            {
                "kind": field.key.removeprefix("force_validated_"),
                "name": field.name,
                "label": field.label,
                "help": field.help,
            }
            for field in section.fields
        ]

    def project_settings(self, page_id: str) -> dict[str, Any]:
        """What a project decides for itself, and what the file decides when it does not.

        `global` is what the runner would apply without the project's own
        switches — the file's, defaults included — so that a page can show it
        as it stands, and fill the project's in with it when they are turned on.
        """
        bare = project_settings.key(page_id)
        globally = {kind: self.config.runner.forces_validation(kind) for kind in kinds_module.KINDS}
        own = project_settings.validation(bare)
        return {
            "id": bare,
            "validation": {
                "own": own is not None,
                "values": own if own is not None else globally,
                "global": globally,
                "fields": self._validation_fields(),
            },
            "ideas": self._project_ideas(bare),
            "local_ci": self._project_local_ci(bare),
            "self_review": self._project_self_review(bare),
            "setup": project_settings.setup(bare),
            "preview": {
                **project_settings.preview(bare).as_dict(),
                "chrome": bool(preview.chrome()),
            },
            "plan": self._project_plan(bare),
            "browser": self._project_browser(bare),
            "diagnostic": self._project_diagnostic(bare),
        }

    @staticmethod
    def _project_diagnostic(bare: str) -> dict[str, Any]:
        """What the project's diagnostics may reach, and the vault's entries to choose from."""
        try:
            entries = sorted(str(entry["name"]) for entry in vault_store.listing())
        except (vault.VaultError, sqlite3.Error, OSError):
            entries = []
        return {**project_settings.diagnostic(bare).as_dict(), "entries": entries}

    def _project_name(self, bare: str) -> str:
        return next(
            (
                str(row["name"])
                for row in self.all_projects()["projects"]
                if project_settings.key(row["id"]) == bare
            ),
            "",
        )

    def _project_browser(self, bare: str) -> dict[str, Any]:
        """The browser of the project's external tickets, whose word that is, and its profile."""
        own = project_settings.browser(bare)
        globally = self.config.browser.default
        name = self._project_name(bare)
        return {
            "value": own or globally,
            "own": own is not None,
            "global": globally,
            "missing": browser.missing(),
            "project": name,
            "sites": browser.sites(browser.load(name)) if name else [],
        }

    def _project_plan(self, bare: str) -> dict[str, Any]:
        """The project's rule for « Plan d'abord », and whether the board can tick the box."""
        rule = project_settings.plan(bare)
        return {
            "priority": rule.priority,
            "subtypes": list(rule.subtypes),
            "column": bool(self.runner.plan_flag()),
        }

    def project_notes(self, page_id: str) -> dict[str, Any]:
        """The project's notes: the kept ones sessions read, and the proposals waiting."""
        bare = project_settings.key(page_id)
        return {
            "id": bare,
            **notes.read(bare),
            "limit": notes.NOTE_LIMIT,
            "capacity": notes.KEPT_LIMIT,
        }

    def save_project_notes(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Keep, drop, add, edit or delete a note: one `action` of the five, with its text or index."""
        bare = project_settings.key(page_id)
        action = payload.get("action")
        text = payload.get("text", "")
        index = payload.get("index", -1)
        if not isinstance(text, str) or not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("a note is text, and a kept one is told by its place")
        row = next(
            (
                item
                for item in self.all_projects()["projects"]
                if project_settings.key(item["id"]) == bare
            ),
            None,
        )
        name = str(row["name"]) if row else ""
        if action == "keep":
            notes.keep(bare, name, text, str(payload.get("edited", "")))
        elif action == "drop":
            notes.drop(bare, name, text)
        elif action == "add":
            notes.add(bare, name, text)
        elif action == "edit":
            notes.edit(bare, name, index, text)
        elif action == "delete":
            notes.delete(bare, name, index)
        else:
            raise ValueError("say what to do with the notes: keep, drop, add, edit or delete")
        self.hub.publish("settings", project=bare)
        return self.project_notes(bare)

    def _project_self_review(self, bare: str) -> dict[str, Any]:
        """Whether a project's branches are reviewed before their pull request, and whose word it is."""
        own = project_settings.self_review(bare)
        globally = self.config.runner.self_review
        return {
            "enabled": own if own is not None else globally,
            "own": own is not None,
            "global": globally,
        }

    def _project_local_ci(self, bare: str) -> dict[str, Any]:
        """The project's local CI: whether it runs, whose word that is, what runs it — and Docker."""
        own = project_settings.local_ci(bare)
        docker = local_ci.docker()
        globally = self.config.runner.local_ci
        return {
            "enabled": own["enabled"] if own["enabled"] is not None else globally,
            "own": own["enabled"] is not None,
            "global": globally,
            "command": own["command"],
            "docker": docker.available,
            "unavailable": settings_module.unavailable_for("docker", docker),
        }

    def _project_ideas(self, bare: str) -> dict[str, Any]:
        """Whether ideas are found for a project on a schedule, and whose word it is."""
        wanted = idea_schedule.plan(self.config.runner)
        name = next(
            (
                row["name"]
                for row in self.all_projects()["projects"]
                if project_settings.key(row["id"]) == bare
            ),
            "",
        )
        own = project_settings.ideas(bare)
        return {
            "enabled": idea_schedule.covers(wanted, bare, name, own),
            "own": own is not None,
            "schedule": wanted.schedule,
        }

    def save_project_settings(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Give a project its own settings, or hand them back to the file.

        `validation.own` false forgets the project's switches; true keeps those
        sent, type by type, and a type left out is off — never the file's, which
        would make a project's choice change the day somebody edits config.toml.
        """
        bare = project_settings.key(page_id)
        validation = payload.get("validation")
        finding = payload.get("ideas")
        checking = payload.get("local_ci")
        preparing = payload.get("setup")
        photographing = payload.get("preview")
        planned = payload.get("plan")
        reviewing = payload.get("self_review")
        browsing = payload.get("browser")
        investigating = payload.get("diagnostic")
        access = None
        if validation is None and isinstance(investigating, dict):
            if "ready" in investigating and not isinstance(investigating["ready"], bool):
                raise ValueError("say whether fix tickets go straight to Ready")
            access = diagnostic.checked(investigating)
        elif validation is None and isinstance(browsing, dict):
            if browsing.get("value") not in config_module.BROWSERS:
                raise ValueError("say which browser the project's external tickets use")
        elif validation is None and isinstance(planned, dict):
            threshold = planned.get("priority")
            if threshold is not None and (
                isinstance(threshold, bool)
                or not isinstance(threshold, int)
                or not 0 <= threshold <= 100
            ):
                raise ValueError("a priority is a number from 0 to 100, or none")
            chosen = planned.get("subtypes", [])
            if not isinstance(chosen, list) or any(key not in subtypes.KEYS for key in chosen):
                raise ValueError("say which sub-types are planned first")
        elif validation is None and isinstance(photographing, dict):
            if not all(
                isinstance(photographing.get(name), str) for name in ("command", "url")
            ) or not isinstance(photographing.get("pages"), list):
                raise ValueError(
                    "say what starts the project, its address and the pages to photograph"
                )
        elif validation is None and isinstance(reviewing, dict):
            if not isinstance(reviewing.get("enabled"), bool):
                raise ValueError(
                    "say whether the project's branches are reviewed before their pull request"
                )
        elif validation is None and isinstance(preparing, dict):
            if not isinstance(preparing.get("command"), str):
                raise ValueError("say what runs in the project's worktrees before a session")
        elif validation is None and isinstance(checking, dict):
            if not isinstance(checking.get("enabled"), bool) or not isinstance(
                checking.get("command", ""), str
            ):
                raise ValueError("say whether the project runs its CI locally, and with what")
        elif validation is None and isinstance(finding, dict):
            if not isinstance(finding.get("enabled"), bool):
                raise ValueError("say whether ideas are found for the project")
        elif not isinstance(validation, dict) or not isinstance(validation.get("own"), bool):
            raise ValueError("say whether the project has its own automatic validation")
        values = (validation or {}).get("values") or {}
        if not isinstance(values, dict) or any(
            kind not in kinds_module.KINDS or not isinstance(value, bool)
            for kind, value in values.items()
        ):
            raise ValueError("automatic validation is a switch for each type of ticket")
        try:
            row = next(
                (
                    item
                    for item in self.projects().values()
                    if project_settings.key(item["id"]) == bare
                ),
                None,
            )
        except store.StoreError:
            row = None
        name = str(row["name"]) if row else ""
        if validation is not None:
            project_settings.set_validation(bare, name, values if validation["own"] else None)
        if isinstance(finding, dict):
            # What the file would say anyway is not a decision of the project's:
            # the switch put back where the file has it hands the question back.
            wanted = idea_schedule.plan(self.config.runner)
            agrees = idea_schedule.covers(wanted, bare, name, None) == finding["enabled"]
            project_settings.set_ideas(bare, name, None if agrees else finding["enabled"])
            self.hub.publish("ideas", settings=True)
        if isinstance(checking, dict):
            wanted = checking["enabled"]
            docker = local_ci.docker()
            if wanted and not docker.available:
                raise ValueError(settings_module.unavailable_for("docker", docker))
            # The file's own answer is not a decision of the project's, as for ideas.
            agrees = wanted == self.config.runner.local_ci
            project_settings.set_local_ci(
                bare, name, None if agrees else wanted, str(checking.get("command", ""))
            )
        if isinstance(preparing, dict):
            project_settings.set_setup(bare, name, preparing["command"])
        if isinstance(photographing, dict):
            project_settings.set_preview(bare, name, preview.parse(photographing))
        if isinstance(planned, dict):
            project_settings.set_plan(bare, name, planning.rule(planned))
        if isinstance(reviewing, dict):
            # The file's own answer is not a decision of the project's, as for ideas.
            agrees = reviewing["enabled"] == self.config.runner.self_review
            project_settings.set_self_review(bare, name, None if agrees else reviewing["enabled"])
        if access is not None:
            project_settings.set_diagnostic(bare, name, access)
        if isinstance(browsing, dict):
            # The file's own answer is not a decision of the project's, as for ideas.
            agrees = browsing["value"] == self.config.browser.default
            project_settings.set_browser(bare, name, None if agrees else browsing["value"])
        self.hub.publish("settings", project=bare)
        return self.project_settings(bare)

    # -- the standing context -------------------------------------------------

    def context(self) -> dict[str, Any]:
        """What reaches every ticket before the ticket itself does.

        Read as text rather than as blocks, which is what the runner puts in the
        prompt anyway — so what this pane shows is exactly what an agent is told,
        and editing it here is editing that.
        """
        space = self.runner.workspace
        return {
            "text": space.context,
            "page": space.context_page,
            # No page to write to is not an error, it is a workspace without a
            # context row — the pane says so rather than offering a save button
            # that could only fail.
            "editable": bool(space.context_page),
        }

    def save_context(self, text: str) -> dict[str, Any]:
        """Rewrite the standing context. The one page the console replaces.

        Replacing, not appending: this is a value, not a history — saving it
        twice must leave one text, not two copies of it under each other. Every
        other write in this console appends, and for the opposite reason.
        """
        space = self.runner.workspace
        if not space.context_page:
            raise ValueError("this board has no context page to write to")
        self.runner.client.replace_markdown(space.context_page, text)
        # The workspace was resolved with the old text in it.
        self.forget()
        self.hub.publish("context", saved=True)
        return {"ok": True, "text": text.strip()}

    # -- what Ponos remembers --------------------------------------------------

    def memories(
        self, scope: str = "", kind: str = "", status: str = "", search: str = ""
    ) -> dict[str, Any]:
        """The memories, filtered; `scope` is "" for every scope, "global", or a project's id."""
        names = {
            project_settings.key(item["id"]): str(item["name"])
            for item in self.all_projects()["projects"]
        }
        wanted: str | None = None
        if scope == "global":
            wanted = ""
        elif scope:
            wanted = project_settings.key(scope)
        shown = []
        for item in memory.listing(scope=wanted, kind=kind, status=status, search=search):
            shown.append(
                {
                    **item,
                    "scope_name": names.get(item["scope"], item["scope"]) if item["scope"] else "",
                }
            )
        folder = memory.files_folder(self.config.runner.workspace_root)
        return {
            "memories": shown,
            "kinds": list(memory.KINDS),
            "auto_accept": memory.options()[memory.AUTO_ACCEPT],
            "importable": len(memory.importable(folder)),
            "limit": memory.FACT_LIMIT,
            "capacity": memory.PROMPT_LIMIT,
        }

    def _memory_scope(self, payload: dict[str, Any]) -> str | None:
        scope = payload.get("scope")
        if scope is None:
            return None
        if not isinstance(scope, str):
            raise ValueError("a scope is “global” or a project")
        return "" if scope in ("", "global") else project_settings.key(scope)

    def memory_add(self, payload: dict[str, Any]) -> dict[str, Any]:
        made = memory.add(
            str(payload.get("text", "")),
            str(payload.get("kind") or "preference"),
            self._memory_scope(payload) or "",
        )
        self.hub.publish("memory", id=made["id"])
        return self.memories()

    def memory_change(self, identifier: int, payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("text")
        kind = payload.get("kind")
        memory.edit(
            identifier,
            text=text if isinstance(text, str) else None,
            kind=kind if isinstance(kind, str) else None,
            scope=self._memory_scope(payload),
        )
        self.hub.publish("memory", id=identifier)
        return self.memories()

    def memory_decide(self, identifier: int, action: str) -> dict[str, Any]:
        """Accept or refuse a proposal, or delete a memory."""
        if action == "accept":
            memory.accept(identifier)
        elif action == "refuse":
            memory.refuse(identifier)
        elif action == "delete":
            memory.delete(identifier)
        else:
            raise ValueError("say what to do with the memory: accept, refuse or delete")
        self.hub.publish("memory", id=identifier)
        return self.memories()

    def memory_import(self) -> dict[str, Any]:
        """Read the assistant's memory files into the memory, once each."""
        taken = memory.import_files(memory.files_folder(self.config.runner.workspace_root))
        self.hub.publish("memory", imported=taken)
        return {**self.memories(), "imported": taken}

    def memory_auto_accept(self, on: bool) -> dict[str, Any]:
        memory.set_option(memory.AUTO_ACCEPT, on)
        self.hub.publish("memory", auto_accept=on)
        return self.memories()

    # -- the library of reference files ------------------------------------------

    def library(self, project: str = "", tag: str = "", search: str = "") -> dict[str, Any]:
        """The library, filtered; `project` keeps the files a session of that project is told."""
        names = {
            project_settings.key(item["id"]): str(item["name"])
            for item in self.all_projects()["projects"]
        }
        shown = []
        for item in library.listing(project=project, tag=tag, search=search):
            shown.append(
                {
                    **{key: value for key, value in item.items() if key != "stored"},
                    "path": str(library.path_of(item)),
                    "project_names": [names.get(key, key) for key in item["projects"]],
                }
            )
        count, total = library.used()
        return {
            "files": shown,
            "tags": library.tags(),
            "count": count,
            "total": total,
            "max_mb": self.config.web.library_max_mb,
        }

    def library_keep(self, path: Path, name: str) -> dict[str, Any]:
        """Keep a conversation's attachment in the library, as it is."""
        kept = library.keep_file(path, name, self.library_limit())
        self.hub.publish("library", id=kept["id"])
        return {**self.library(), "kept": self.library_shown(kept)}

    def library_shown(self, item: dict[str, Any]) -> dict[str, Any]:
        """A library file as the page reads it: no stored name, its path, its projects by name."""
        names = {
            project_settings.key(found["id"]): str(found["name"])
            for found in self.all_projects()["projects"]
        }
        return {
            **{key: value for key, value in item.items() if key != "stored"},
            "path": str(library.path_of(item)),
            "project_names": [names.get(key, key) for key in item["projects"]],
        }

    def library_limit(self) -> int:
        return self.config.web.library_max_mb * 1024 * 1024

    def library_change(self, identifier: int, payload: dict[str, Any]) -> dict[str, Any]:
        name, description = payload.get("name"), payload.get("description")
        library.edit(
            identifier,
            name=name if isinstance(name, str) else None,
            description=description if isinstance(description, str) else None,
            tag_list=payload.get("tags"),
            project_list=payload.get("projects"),
        )
        self.hub.publish("library", id=identifier)
        return self.library()

    def library_delete(self, identifier: int) -> dict[str, Any]:
        library.delete(identifier)
        self.hub.publish("library", id=identifier)
        return self.library()

    # -- the skills Ponos gives its sessions -----------------------------------

    def _repository_skills(self) -> list[dict[str, Any]]:
        """The skills the repositories already hold, each with the project it comes from."""
        found: list[dict[str, Any]] = []
        for project in self.all_projects()["projects"]:
            if project.get("kind") != "code":
                continue
            try:
                where = self.runner.resolver.locate(
                    project["name"],
                    project.get("configured") or project.get("path") or "",
                    project.get("repository") or "",
                )
            except OSError:
                where = None
            if where is None:
                continue
            for item in skills.in_repository(where):
                found.append(
                    {
                        "name": item["name"],
                        "description": item["description"],
                        "project": project["id"],
                        "project_name": project["name"],
                        "repository": project.get("repository") or str(where),
                    }
                )
        return found

    def skills(self) -> dict[str, Any]:
        """Ponos's skills with where each applies, and the repositories' own, read only."""
        names = {
            project_settings.key(item["id"]): str(item["name"])
            for item in self.all_projects()["projects"]
            if item["id"]
        }
        from_repositories = self._repository_skills()
        shown = []
        for item in skills.listing():
            scope = item["scope"]
            clashes = [
                {"project": other["project"], "project_name": other["project_name"]}
                for other in from_repositories
                if other["name"] == item["name"]
                and (not scope or project_settings.key(other["project"]) in scope)
            ]
            shown.append(
                {
                    **item,
                    "scope_names": [names.get(key, key) for key in scope],
                    "conflicts": clashes,
                }
            )
        return {
            "skills": shown,
            "repositories": from_repositories,
            "file_limit": skills.FILE_LIMIT,
        }

    def skill(self, identifier: int) -> dict[str, Any]:
        return skills.get(identifier)

    def skill_add(self, payload: dict[str, Any]) -> dict[str, Any]:
        made = skills.create(
            str(payload.get("name", "")),
            str(payload.get("description", "")),
            str(payload.get("body", "")),
            payload.get("scope"),
            enabled=payload.get("enabled") is not False,
        )
        self.hub.publish("skills", id=made["id"])
        return made

    def skill_change(self, identifier: int, payload: dict[str, Any]) -> dict[str, Any]:
        def text(key: str) -> str | None:
            value = payload.get(key)
            return value if isinstance(value, str) else None

        changed = skills.update(
            identifier,
            name=text("name"),
            description=text("description"),
            body=text("body"),
            scope=payload.get("scope"),
            scope_given="scope" in payload,
            enabled=payload["enabled"] if isinstance(payload.get("enabled"), bool) else None,
        )
        self.hub.publish("skills", id=identifier)
        return changed

    def skill_delete(self, identifier: int) -> None:
        skills.delete(identifier)
        self.hub.publish("skills", id=identifier)

    def skill_attach(self, identifier: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Files added to a skill: `{files: [{path, data}]}`, data in base64."""
        files = skills.decode(payload.get("files"))
        changed = skills.get(identifier)
        for path, content in files.items():
            changed = skills.put_file(identifier, path, content)
        self.hub.publish("skills", id=identifier)
        return changed

    def skill_detach(self, identifier: int, path: str) -> dict[str, Any]:
        changed = skills.remove_file(identifier, path)
        self.hub.publish("skills", id=identifier)
        return changed

    def skill_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A skill read from a folder (`files`) or a .zip (`archive`, base64)."""
        scope = payload.get("scope")
        if isinstance(payload.get("archive"), str):
            try:
                data = base64.b64decode(payload["archive"], validate=True)
            except ValueError as error:
                raise ValueError("l'archive envoyée est illisible") from error
            made = skills.import_archive(data, scope=scope)
        else:
            made = skills.import_files(skills.decode(payload.get("files")), scope=scope)
        self.hub.publish("skills", id=made["id"])
        return made
