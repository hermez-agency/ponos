"""Les déclencheurs entrants vus de la console : les gérer, et recevoir un appel.

La gestion (liste, création, révocation) est de l'API de la page, derrière le
jeton comme le reste. Recevoir un appel ne l'est pas : `POST /api/hooks/<clé>`
vient d'un outil qui ne sait rien dire d'autre que son adresse, et c'est la clé
qui la garde (voir `triggers.py`). Une clé inconnue et une clé révoquée
répondent la même 404, sans un mot de plus : la réponse ne dit pas laquelle
des deux, ni qu'un déclencheur existe.

Le ticket naît par `create_ticket`, comme celui du bouton *Nouveau ticket* : un
brouillon par défaut. Ce qu'un outil envoie est du texte que n'importe qui a pu
écrire (le titre d'une erreur Sentry, le message d'un commit) ; un déclencheur
qui part en *Prêt* donne donc à cet inconnu une session Claude. C'est un choix
qui se fait en connaissance de cause, `guide/tickets.md` le dit.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .. import ids, triggers
from .base import Base

logger = logging.getLogger(__name__)

# Un JSON d'outil tient dans quelques ko ; au-delà, c'est une erreur.
MAX_EVENT = 256 * 1024

# Deux livraisons du même événement arrivent parfois ensemble : une seule crée.
_CREATING = threading.Lock()


class Hooks(Base):
    def all_triggers(self) -> dict[str, Any]:
        """Ce que l'onglet Déclencheurs affiche : les clés, les préréglages, les projets."""
        known = sorted(self.projects().values(), key=lambda project: project["name"].lower())
        names = {ids.bare(project["id"]): project["name"] for project in known}
        return {
            "hooks": [self._hook_shown(hook, names) for hook in triggers.listing()],
            "presets": [
                {
                    "key": preset.key,
                    "name": preset.name,
                    "title": preset.title,
                    "brief": preset.brief,
                    "kind": preset.kind,
                    "subtype": preset.subtype,
                }
                for preset in triggers.PRESETS.values()
            ],
            "projects": [{"id": ids.bare(id_), "name": name} for id_, name in names.items()],
            "per_hour": triggers.DEFAULT_PER_HOUR,
        }

    @staticmethod
    def _hook_shown(hook: triggers.Hook, names: dict[str, str]) -> dict[str, Any]:
        return {
            "id": hook.id,
            "name": hook.name,
            "preset": hook.preset,
            "project": hook.project,
            "project_name": names.get(hook.project, ""),
            "kind": hook.kind,
            "subtype": hook.subtype,
            "priority": hook.priority,
            "status": hook.status,
            "title": hook.title,
            "brief": hook.brief,
            "per_hour": hook.per_hour,
            "created_at": hook.created_at,
            "revoked": hook.revoked,
            "last_at": hook.last_at,
            "count": hook.count,
        }

    def create_trigger(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Un déclencheur de plus ; sa clé n'est dite qu'ici."""
        project = ids.bare(str(payload.get("project") or ""))
        known = {ids.bare(project_id): item for project_id, item in self.projects().items()}
        if project not in known:
            raise triggers.Refused("project", "Choisis le projet où naissent les tickets.")
        hook, key = triggers.create({**payload, "project": project})
        names = {identifier: item["name"] for identifier, item in known.items()}
        return {"hook": self._hook_shown(hook, names), "key": key}

    def revoke_trigger(self, hook_id: str) -> dict[str, Any]:
        if not triggers.revoke(hook_id):
            raise LookupError("no such trigger")
        return {"id": hook_id}

    def receive(self, key: str, raw: bytes) -> tuple[int, dict[str, Any], dict[str, str]]:
        """Un appel de l'outil : le statut, la réponse, et les en-têtes qui vont avec."""
        hook = triggers.find(key)
        if hook is None:
            return 404, {"error": "no such route"}, {}
        try:
            event = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "the body is not JSON"}, {}
        if not triggers.accepts(hook.preset, event):
            # Ce n'est pas une erreur : un `ping`, un workflow réussi.
            return 200, {"ignored": True}, {}
        name = triggers.identifier(hook.preset, hook.event, event, raw)
        with _CREATING:
            claimed = triggers.claim(hook, name)
            if claimed.state == "duplicate":
                return 200, {"duplicate": True, "ticket": claimed.ticket}, {}
            if claimed.state == "limited":
                logger.warning("hook %s: %d tickets an hour reached", hook.id, hook.per_hour)
                return (
                    429,
                    {"error": f"{hook.per_hour} tickets an hour at most for this key"},
                    {"Retry-After": str(claimed.wait)},
                )
            try:
                made = self._ticket_from(hook, event)
            except BaseException:
                triggers.settle(hook, name, "")
                raise
            triggers.settle(hook, name, made)
        triggers.purge()
        return 201, {"ticket": made, "status": hook.status}, {}

    def _ticket_from(self, hook: triggers.Hook, event: Any) -> str:
        title = triggers.render(hook.title, event, triggers.TITLE_MAX)
        title = " ".join(title.split()) or hook.name
        brief = triggers.tidy(triggers.render(hook.brief, event, triggers.VALUE_MAX))
        brief = f"{brief}\n\n_Créé par le déclencheur « {hook.name} »._".strip()
        made = self.create_ticket(
            title[: triggers.TITLE_MAX],
            brief[: triggers.BRIEF_MAX],
            hook.project,
            ready=hook.status == "ready",
            priority=hook.priority,
            kind=hook.kind,
            subtype=hook.subtype,
        )
        return str(made["id"]).replace("-", "")
