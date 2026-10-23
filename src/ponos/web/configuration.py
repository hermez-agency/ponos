"""What the console lets you set: the file, a project's own settings, the standing context.

Three things written in three places — `config.toml`, `ponos.db` and a page of
the board — and one chapter for them, because to whoever opens the settings
they are one question: what will the runner do, and where is that decided.
Every save here drops what was read under the old answer, since a token, a
workspace or a property name changed is a different board.
"""

from __future__ import annotations

from typing import Any

from .. import idea_schedule, project_settings, store
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
        if validation is None and isinstance(finding, dict):
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
            "where": self.config.notion.page("context"),
            "storage": self.config.storage.mode,
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
            raise ValueError(
                f"this workspace has no “{self.config.notion.page('context')}” page to write to"
            )
        self.runner.client.replace_markdown(space.context_page, text)
        # The workspace was resolved with the old text in it.
        self.forget()
        self.hub.publish("context", saved=True)
        return {"ok": True, "text": text.strip()}
