"""Les déclencheurs entrants : une URL qu'un outil appelle, et un ticket qui naît.

Un ticket naissait de la main de quelqu'un, d'une récurrence, d'une idée ou de
« Réparer main ». Une erreur de production, une CI qui casse : personne ne la
transformait en ticket tant qu'un humain ne la lisait pas. Un déclencheur est
une clé dans l'adresse (`POST /api/hooks/<clé>`) avec ce qu'il faut pour
fabriquer le ticket — projet, type, priorité, statut d'arrivée, gabarits.

**La clé est dans l'URL parce que les outils ne savent rien dire d'autre.**
Sentry et GitHub n'envoient ni en-tête d'autorisation sur mesure ni jeton de
portage : l'adresse *est* le secret, comme celle d'un webhook Slack. Elle n'est
donc gardée que sous forme de SHA-256 (la base dit quel déclencheur existe,
jamais sa clé), montrée une seule fois à la création, et le journal du
console ne l'écrit jamais (`mask`).

**Un identifiant d'événement, un ticket.** Les outils rejouent : Sentry
renvoie un webhook qui a mis trop de temps, GitHub propose « Redeliver ». Le
couple (déclencheur, événement) est la clé primaire de `hook_events`, inscrit
*avant* de créer le ticket : deux livraisons simultanées du même événement ne
passent pas toutes les deux. Quand le JSON ne dit pas son identifiant, c'est
le SHA-256 du corps qui en tient lieu — le même envoi deux fois n'est qu'un
événement.

**Un plafond par heure et par clé**, compté sur ce que le déclencheur a
créé : un outil pris de folie ne remplit pas le tableau. Un événement refusé
pour cela n'est pas inscrit, et passe à la livraison suivante.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from . import db, kinds, priority, subtypes

# Ce que `POST /api/hooks/<clé>` est, et le chemin que `ponos tailscale` publie.
ROUTE = "/api/hooks"

# Les tickets qu'une clé peut créer par heure, quand elle ne dit rien d'autre.
DEFAULT_PER_HOUR = 10
MAX_PER_HOUR = 1000

STATUSES = ("draft", "ready")

# Une clé : ce que `secrets.token_urlsafe(24)` écrit. Autre chose n'est pas une
# clé, et n'a pas besoin d'aller jusqu'à la base.
KEY = re.compile(r"[A-Za-z0-9_-]{20,64}")

# Les gabarits : `{{ event.data.issue.title }}`, ou `{{ a | b }}` — le premier
# chemin qui donne quelque chose.
SLOT = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")

# Ce qu'un gabarit peut produire, pour qu'un JSON énorme ne fasse pas un ticket énorme.
TITLE_MAX = 200
VALUE_MAX = 2000
BRIEF_MAX = 20000


class Refused(ValueError):
    """Un déclencheur qui ne sera pas créé, et le champ qui dit pourquoi."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Preset:
    """Ce qu'un outil connu envoie, et les gabarits qui en font un ticket."""

    key: str
    name: str
    title: str
    brief: str
    # Où se lit l'identifiant de l'événement dans son JSON.
    event: str
    kind: str = "code"
    subtype: str = ""


PRESETS: dict[str, Preset] = {
    "sentry": Preset(
        key="sentry",
        name="Sentry — issue créée",
        title="[Sentry] {{ event.data.issue.title }}",
        brief=(
            "Sentry a ouvert une issue.\n\n"
            "- Projet : {{ event.data.issue.project.slug | event.project_name }}\n"
            "- Erreur : {{ event.data.issue.title | event.message }}\n"
            "- Où : {{ event.data.issue.culprit | event.culprit }}\n"
            "- Niveau : {{ event.data.issue.level | event.level }}\n"
            "- Lien : {{ event.data.issue.web_url | event.data.issue.permalink | event.url }}\n\n"
            "Retrouve la cause dans le code, corrige-la et ajoute le test qui l'aurait vue."
        ),
        event="event.data.issue.id | event.id",
        subtype="bug",
    ),
    "github": Preset(
        key="github",
        name="GitHub — workflow en échec sur la branche par défaut",
        title="[CI] {{ event.workflow_run.name }} en échec sur {{ event.workflow_run.head_branch }}",
        brief=(
            "Le workflow « {{ event.workflow_run.name }} » a échoué sur "
            "{{ event.repository.full_name }} "
            "({{ event.workflow_run.head_branch }}, {{ event.workflow_run.head_sha }}).\n\n"
            "- Exécution : {{ event.workflow_run.html_url }}\n"
            "- Commit : {{ event.workflow_run.head_commit.message }}\n\n"
            "Lis le journal de l'exécution, trouve pourquoi elle échoue et corrige-le."
        ),
        event="event.workflow_run.id",
        subtype="bug",
    ),
    "generic": Preset(
        key="generic",
        name="Webhook quelconque",
        title="{{ event.title | event.message | event.name }}",
        brief=(
            "{{ event.body | event.description | event.message }}\n\n"
            "- Lien : {{ event.url | event.link | event.html_url }}"
        ),
        event="event.id | event.event_id",
    ),
}


def accepts(preset: str, event: Any) -> bool:
    """Le JSON reçu est un événement que ce préréglage transforme en ticket.

    GitHub envoie aussi `ping`, et chaque workflow qui réussit ou démarre ;
    Sentry envoie aussi `resolved`, `assigned`. Ce que le préréglage ne veut
    pas n'est pas une erreur : l'outil recevrait une 4xx, la rejouerait puis
    désactiverait le webhook.
    """
    if not isinstance(event, dict):
        return False
    if preset == "sentry":
        return event.get("action") == "created" and bool(_dig(event, "data.issue"))
    if preset == "github":
        run = event.get("workflow_run")
        if event.get("action") != "completed" or not isinstance(run, dict):
            return False
        repository = event.get("repository") or {}
        default = repository.get("default_branch") if isinstance(repository, dict) else ""
        return (
            run.get("conclusion") == "failure"
            and bool(default)
            and run.get("head_branch") == default
        )
    return True


# -- gabarits -----------------------------------------------------------------


def _dig(event: Any, path: str) -> Any:
    """La valeur au bout de `a.b.0.c` — None quand le chemin s'arrête en route."""
    found = event
    for part in path.strip().split("."):
        if isinstance(found, dict) and part in found:
            found = found[part]
        elif isinstance(found, list) and part.isdigit() and int(part) < len(found):
            found = found[int(part)]
        else:
            return None
    return found


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _event_path(path: str) -> str:
    # `event.x` et `x` disent la même chose : le JSON reçu s'appelle « event ».
    path = path.strip()
    return path[len("event.") :] if path.startswith("event.") else path


def render(template: str, event: Any, limit: int = VALUE_MAX) -> str:
    """Le gabarit rempli avec le JSON reçu ; ce qui manque donne un texte vide.

    Rien d'autre qu'un chemin : un gabarit qui viendrait d'un réglage n'exécute
    ni n'évalue rien, et ce que le JSON contient ne se relit pas comme un gabarit.
    """

    def fill(found: re.Match[str]) -> str:
        for path in found.group(1).split("|"):
            value = _text(_dig(event, _event_path(path))) if path.strip() != "event" else ""
            if value:
                return value[:limit]
        return ""

    return SLOT.sub(fill, template)


def identifier(preset: str, template: str, event: Any, raw: bytes) -> str:
    """Ce qui dit que deux livraisons sont le même événement."""
    paths = template or PRESETS.get(preset, PRESETS["generic"]).event
    found = render("{{ " + paths + " }}", event, 200)
    if found:
        # Avec la livraison de GitHub : un workflow rejoué porte un autre `run_attempt`.
        attempt = _text(_dig(event, "workflow_run.run_attempt")) if preset == "github" else ""
        return f"{found}#{attempt}" if attempt else found
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def tidy(text: str) -> str:
    """Le brief rempli, sans les lignes que des valeurs vides ont laissées en plan."""
    lines = [line.rstrip() for line in text.splitlines()]
    kept = [line for line in lines if not re.fullmatch(r"\s*[-*]\s*[^:]{0,40}:\s*", line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


# -- clés ---------------------------------------------------------------------


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def mask(path: str) -> str:
    """Un chemin sans la clé qu'il porte, pour le journal et les messages."""
    if path == ROUTE or path.startswith(ROUTE + "/"):
        return ROUTE + "/…"
    return path


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


@dataclass(frozen=True)
class Hook:
    id: str
    name: str
    preset: str
    project: str
    kind: str
    subtype: str
    priority: int
    status: str
    title: str
    brief: str
    event: str
    per_hour: int
    created_at: str
    revoked_at: str
    last_at: str = ""
    count: int = 0

    @property
    def revoked(self) -> bool:
        return bool(self.revoked_at)


_COLUMNS = (
    "id, name, preset, project, kind, subtype, priority, status, title, brief, event,"
    " per_hour, created_at, COALESCE(revoked_at, '')"
)


def _hook(row: sqlite3.Row | tuple[Any, ...], last: str = "", count: int = 0) -> Hook:
    (id_, name, preset, project, kind, subtype, score, status, title, brief, event) = row[:11]
    return Hook(
        id_,
        name,
        preset,
        project,
        kind,
        subtype,
        score,
        status,
        title,
        brief,
        event,
        row[11],
        row[12],
        row[13],
        last,
        count,
    )


def clean(values: dict[str, Any]) -> dict[str, Any]:
    """Ce que le formulaire dit, vérifié — ou le `Refused` qui désigne le champ."""
    name = " ".join(str(values.get("name") or "").split())[:80]
    if not name:
        raise Refused("name", "Un déclencheur a besoin d'un nom.")
    preset = str(values.get("preset") or "generic")
    if preset not in PRESETS:
        raise Refused("preset", f"Préréglage inconnu : « {preset} ».")
    chosen = PRESETS[preset]
    kind = str(values.get("kind") or chosen.kind).strip()
    if kind and kind not in kinds.KINDS:
        raise Refused("kind", f"Type inconnu : « {kind} ».")
    subtype = str(values.get("subtype") if values.get("subtype") is not None else chosen.subtype)
    subtype = subtype.strip()
    if subtype and subtype not in subtypes.KEYS:
        raise Refused("subtype", f"Sous-type inconnu : « {subtype} ».")
    status = str(values.get("status") or "draft")
    if status not in STATUSES:
        raise Refused("status", "Le statut d'arrivée est Brouillon ou Prêt.")
    try:
        score = priority.given(values.get("priority", ""))
    except (TypeError, ValueError) as error:
        raise Refused("priority", "La priorité est un nombre de 0 à 100.") from error
    try:
        per_hour = int(values.get("per_hour") or DEFAULT_PER_HOUR)
    except (TypeError, ValueError) as error:
        raise Refused("per_hour", "Le plafond est un nombre de tickets par heure.") from error
    if not 1 <= per_hour <= MAX_PER_HOUR:
        raise Refused("per_hour", f"Le plafond va de 1 à {MAX_PER_HOUR} tickets par heure.")
    title = str(values.get("title") if values.get("title") is not None else "").strip()
    brief = str(values.get("brief") if values.get("brief") is not None else "").strip()
    return {
        "name": name,
        "preset": preset,
        "project": str(values.get("project") or "").replace("-", ""),
        "kind": kind,
        "subtype": subtype if kind in ("", "code") else "",
        "priority": score,
        "status": status,
        "title": title or chosen.title,
        "brief": brief or chosen.brief,
        "event": str(values.get("event") or "").strip(),
        "per_hour": per_hour,
    }


def create(values: dict[str, Any]) -> tuple[Hook, str]:
    """Un déclencheur, et sa clé — la seule fois qu'elle est dite."""
    kept = clean(values)
    key = secrets.token_urlsafe(24)
    identifier_ = secrets.token_hex(6)
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO hooks (id, digest, name, preset, project, kind, subtype, priority,"
            " status, title, brief, event, per_hour, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier_,
                digest(key),
                kept["name"],
                kept["preset"],
                kept["project"],
                kept["kind"],
                kept["subtype"],
                kept["priority"],
                kept["status"],
                kept["title"],
                kept["brief"],
                kept["event"],
                kept["per_hour"],
                _stamp(_now()),
            ),
        )
        row = connection.execute(f"SELECT {_COLUMNS} FROM hooks WHERE id = ?", (identifier_,))
        return _hook(row.fetchone()), key


def listing() -> list[Hook]:
    """Tous les déclencheurs, les vivants d'abord, avec leur dernier appel."""
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            f"SELECT {_COLUMNS}, (SELECT COALESCE(MAX(at), '') FROM hook_events"
            " WHERE hook = hooks.id AND ticket != ''),"
            " (SELECT COUNT(*) FROM hook_events WHERE hook = hooks.id AND ticket != '')"
            " FROM hooks ORDER BY revoked_at IS NOT NULL, created_at DESC"
        ).fetchall()
    return [_hook(row, row[14], row[15]) for row in rows]


def revoke(identifier_: str) -> bool:
    """La clé ne répond plus. Vrai quand le déclencheur existait et vivait encore."""
    with db.transaction() as connection:
        done = connection.execute(
            "UPDATE hooks SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (_stamp(_now()), identifier_),
        )
        return done.rowcount > 0


def find(key: str) -> Hook | None:
    """Le déclencheur vivant de cette clé — None pour une clé inconnue ou révoquée."""
    if not KEY.fullmatch(key):
        return None
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            f"SELECT {_COLUMNS} FROM hooks WHERE digest = ? AND revoked_at IS NULL",
            (digest(key),),
        ).fetchone()
    return _hook(row) if row else None


# -- livraisons ---------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """Ce que la livraison obtient : sa place, un doublon, ou l'attente."""

    state: str  # "new", "duplicate" ou "limited"
    ticket: str = ""
    wait: int = 0


def claim(hook: Hook, event: str) -> Claim:
    """Inscrire l'événement avant de créer son ticket — ou dire pourquoi pas."""
    now = _now()
    with db.transaction() as connection:
        seen = connection.execute(
            "SELECT ticket FROM hook_events WHERE hook = ? AND event = ?", (hook.id, event)
        ).fetchone()
        if seen:
            return Claim("duplicate", seen[0])
        since = _stamp(now - timedelta(hours=1))
        recent = connection.execute(
            "SELECT COUNT(*), MIN(at) FROM hook_events WHERE hook = ? AND at > ?",
            (hook.id, since),
        ).fetchone()
        if recent[0] >= hook.per_hour:
            oldest = datetime.fromisoformat(recent[1])
            wait = int((oldest + timedelta(hours=1) - now).total_seconds()) + 1
            return Claim("limited", wait=max(wait, 1))
        connection.execute(
            "INSERT INTO hook_events (hook, event, at) VALUES (?, ?, ?)",
            (hook.id, event, _stamp(now)),
        )
    return Claim("new")


def settle(hook: Hook, event: str, ticket: str) -> None:
    """Le ticket que l'événement a fait ; vide, l'inscription est retirée (rien n'est né)."""
    with db.transaction() as connection:
        if ticket:
            connection.execute(
                "UPDATE hook_events SET ticket = ? WHERE hook = ? AND event = ?",
                (ticket, hook.id, event),
            )
        else:
            connection.execute(
                "DELETE FROM hook_events WHERE hook = ? AND event = ?", (hook.id, event)
            )


def purge(days: int = 30) -> None:
    """Les événements vus il y a plus longtemps que ça : un doublon aussi tardif n'en est plus un."""
    cutoff = _stamp(_now() - timedelta(days=days))
    with db.transaction() as connection:
        connection.execute("DELETE FROM hook_events WHERE at < ?", (cutoff,))
