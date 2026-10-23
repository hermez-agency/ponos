"""The console as an MCP server: the board, read and written from Claude.

From claude.ai, from Claude Code, from a phone: a conversation that can see the
tasks, open one, create one in the right project and answer the question a
blocked one asks — without the Notion connector, and without knowing whether the
board is in Notion or in Markdown files. What a tool hands back is a task, a
project, an idea, a sum of money: never a page, a database or a property. The
`Api` underneath is the console's own, so a task created here is the task the
console's *New ticket* creates, and an answer is the comment the console's
discussion posts — the same road, the same rules, nothing beside them.

**Small on purpose.** Nothing here starts a session, runs a command, touches
the configuration or deletes anything. A task created *ready* is picked up by
the timer like any other ready ticket — that is the runner's decision, on its
cadence, not this server's. The tools that write are few, need the `write`
scope (see `oauth.py`), and each call is written to the journal with the tool,
the moment and the client, refused ones included.

**The protocol, as little of it as a tool server needs.** JSON-RPC over one
HTTP endpoint (the Streamable HTTP transport), each request answered in its
response as JSON: no stream, no session, nothing kept between two requests,
since every tool reads the board fresh. `initialize`, `tools/list`,
`tools/call`, `ping`, and the notifications, which are acknowledged.

**Pasted, and it works.** Adding the connector is its address and nothing
else, as for Leadz: what Claude shows of it — a name, a sentence, the logo —
is in `initialize`, every tool has a title a person reads in the list, and
`whoami` is the first call to try, the one that says the connection holds:
whose console, which client, read or read and write.

The descriptions are French, and long where it helps: they are what Claude
reads to choose a tool, and a vague one is a tool called at the wrong moment.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import __version__, db, ideas, journal, log, state, store, systemd
from .. import config as config_module
from .. import kinds as kinds_module
from . import live
from .api import COLUMNS
from .oauth import READ, WRITE, Grant

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .api import Api

# The versions of the protocol this server speaks, newest first. A client that
# asks for one of them gets it; any other is answered with the newest.
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

# The columns a task can be in, as the tools name them — the console's own keys,
# in the console's own order.
STATUSES = ("draft", *COLUMNS)

# What one answer carries at most: a description is a brief, not a book, and a
# conversation is read for its last turns.
DESCRIPTION_LIMIT = 12_000
MESSAGE_LIMIT = 2_000
MESSAGES = 20
RUNS = 5
LISTED = 50
LISTED_MOST = 200

# What a journal line keeps of the arguments it was called with.
ARGUMENT_LIMIT = 500

# What Claude shows of the connector, beside its name. The icon is the site's,
# not the console's: a console's files are behind its sign-in, and Claude
# fetches the icon without any key.
WEBSITE = "https://the-ponos.app"
DESCRIPTION = (
    "Ponos (the-ponos.app) : les tâches, projets et idées de votre console, ce que fait le "
    "runner et ce qu'il a dépensé ; créer une tâche, répondre à une tâche bloquée, trier les idées."
)
ICONS = [{"src": f"{WEBSITE}/mascot/favicon.svg", "mimeType": "image/svg+xml", "sizes": ["any"]}]

INSTRUCTIONS = """\
Ponos exécute des tâches avec Claude Code : une tâche passée en « ready » est \
reprise par le runner, travaillée dans un worktree git qui lui est propre, et \
revient en pull request ou en document. Ce serveur lit l'état de Ponos et écrit \
peu : créer une tâche, répondre à une tâche bloquée, trier les idées.

- Une tâche « vous attend » (statut blocked) quand une session s'est arrêtée sur \
une question : lisez-la avec get_task, puis répondez avec answer_question — ou \
lisez avec list_solutions ce qui la débloquerait, et appliquez-en une avec \
apply_solution, qui sert aussi à décider d'une tâche en review.
- Créez une tâche en « draft » sauf si la personne demande explicitement qu'elle \
parte tout de suite : une tâche « ready » sera lancée par le runner à sa \
prochaine passe, et coûtera une session.
- Aucun outil ne lance d'exécution, ne lance de commande, ne modifie la \
configuration ni ne supprime quoi que ce soit."""


class ToolError(Exception):
    """A call the tool refuses, said to the model in a sentence it can act on."""


# -- the tools ----------------------------------------------------------------


def _schema(properties: dict | None = None, required: tuple[str, ...] = ()) -> dict:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


TASK_REFERENCE = {
    "type": "string",
    "description": "L'identifiant de la tâche : le long (32 caractères hexadécimaux) ou le court "
    "(8 caractères) que renvoient list_tasks et get_task.",
}

PROJECT_FILTER = {
    "type": "string",
    "description": "Le nom du projet (tel que list_projects le renvoie, sans tenir compte de la "
    "casse) ou son identifiant.",
}

TOOLS: list[dict] = [
    {
        "name": "whoami",
        "title": "Mon compte",
        "scope": READ,
        "description": "Le compte Ponos au nom duquel vous agissez : l'adresse de la console, "
        "l'email de la personne qui s'y connecte, le client connecté (claude.ai, Claude Code…) et "
        "son accès (lecture seule, ou lecture et écriture), où vit le tableau (Notion ou fichiers "
        "Markdown), le nombre de projets et de tâches qui vous attendent. À appeler en premier pour "
        "vérifier que le connecteur marche, ou quand on demande « qui suis-je ? ».",
        "inputSchema": _schema(),
    },
    {
        "name": "list_projects",
        "title": "Projets",
        "scope": READ,
        "description": "Liste les projets de Ponos : nom, identifiant, icône (emoji ou adresse "
        "d'image), dépôt git (« propriétaire/nom ») et genre (« code » quand le projet a un dépôt, "
        "« document » sinon). À appeler pour connaître le nom exact d'un projet avant "
        "list_tasks, create_task ou create_idea.",
        "inputSchema": _schema(),
    },
    {
        "name": "list_tasks",
        "title": "Tâches",
        "scope": READ,
        "description": "Liste les tâches de Ponos, les plus récemment modifiées d'abord, avec "
        "pour chacune son identifiant, son titre, son projet, son statut, son type, sa priorité, "
        "sa pull request et son coût. Statuts : draft (brouillon, jamais lancé), ready (en file, "
        "le runner le prendra à sa prochaine passe), running (session en cours), "
        "blocked (« vous attend » : une session pose une question), review (travail "
        "livré, attend une relecture), validated (relu, en cours de fusion ou de publication), "
        "failed (échec), done "
        "(terminé), cancelled (abandonné, jamais repris). Pour « ce qui m'attend » ou « les tâches bloquées », passer "
        "waiting_for_you=true. Ne renvoie pas le détail d'une tâche : utiliser get_task.",
        "inputSchema": _schema(
            {
                "project": PROJECT_FILTER,
                "status": {
                    "type": "string",
                    "enum": list(STATUSES),
                    "description": "Ne garder que les tâches de ce statut.",
                },
                "waiting_for_you": {
                    "type": "boolean",
                    "description": "true : seulement les tâches qui attendent une réponse "
                    "(statut blocked).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": LISTED_MOST,
                    "description": f"Combien de tâches au plus ({LISTED} par défaut).",
                },
            }
        ),
    },
    {
        "name": "get_task",
        "title": "Détail d'une tâche",
        "scope": READ,
        "description": "Renvoie le détail d'une tâche : sa description (le brief et le compte "
        "rendu des sessions), les derniers échanges de sa discussion (ce que Ponos a dit, ce que "
        "vous avez répondu) et la question en attente s'il y en a une, sa pull request, son coût, "
        "sa session (identifiant, durée, modèle) et ses dernières exécutions. À appeler avant de "
        "répondre à une tâche bloquée, pour lire la question et les options proposées.",
        "inputSchema": _schema({"task": TASK_REFERENCE}, ("task",)),
    },
    {
        "name": "runner_status",
        "title": "Runner et dépenses",
        "scope": READ,
        "description": "Renvoie l'état du runner : la minuterie (active ou non, et sa cadence), "
        "une passe en cours ou non, les sessions en cours et leur tâche, les tâches au statut "
        "running, et les dépenses — aujourd'hui, sur la période demandée et par projet sur cette "
        "période, avec la limite quotidienne si elle est réglée. À appeler pour « que fait "
        "Ponos ? » ou « combien j'ai dépensé ? ».",
        "inputSchema": _schema(
            {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 366,
                    "description": "La période des dépenses, en jours jusqu'à aujourd'hui inclus "
                    "(30 par défaut).",
                }
            }
        ),
    },
    {
        "name": "list_ideas",
        "title": "Idées",
        "scope": READ,
        "description": "Liste les idées que Ponos a proposées (ou qu'on lui a données) pour un "
        "projet, ou pour l'espace de travail entier quand aucun projet n'est donné. Chaque idée a "
        "un identifiant numérique, un titre, une description, un genre (« ticket » : une tâche à "
        "faire ; « project » : un nouveau projet), un état : proposed (en attente d'une "
        "décision), kept (gardée pour plus tard), ticket (devenue une tâche en brouillon), "
        "discarded (jetée) — et un score de pertinence de 0 à 100 avec la ligne qui le justifie "
        "(null : pas encore notée ; 70 et plus : vert, de 40 à 69 : orange, moins de 40 : rouge).",
        "inputSchema": _schema(
            {
                "project": PROJECT_FILTER,
                "status": {
                    "type": "string",
                    "enum": list(ideas.STATUSES),
                    "description": "Ne garder que les idées dans cet état (proposed par défaut).",
                },
            }
        ),
    },
    {
        "name": "create_task",
        "title": "Créer une tâche",
        "scope": WRITE,
        "description": "Crée une tâche dans Ponos, par le même circuit qu'une tâche créée depuis "
        "la console ou le tableau : mêmes règles, même runner. En statut draft (par défaut), elle "
        "attend qu'on la relise ; en ready, le runner la lancera à sa prochaine passe — ne choisir "
        "ready que si la personne le demande. Le projet décide du dépôt où le travail se fait : "
        "vérifier son nom avec list_projects. Sans type, Ponos le déduit lui-même avant de lancer "
        "la tâche. Renvoie l'identifiant de la tâche créée.",
        "inputSchema": _schema(
            {
                "title": {
                    "type": "string",
                    "description": "Le titre : ce qu'il faut faire, en une ligne.",
                },
                "description": {
                    "type": "string",
                    "description": "Le brief, en Markdown : le contexte, ce qui est attendu, quand "
                    "c'est fini, ce qui est hors périmètre.",
                },
                "project": PROJECT_FILTER,
                "type": {
                    "type": "string",
                    "enum": list(kinds_module.KINDS),
                    "description": "code (modifier un dépôt, livré en pull request), writing "
                    "(rédiger un document), external (agir sur un service extérieur), "
                    "publication (publier, après validation humaine).",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Un score de 0 (vraiment pas important) à 100 (à faire tout de "
                    "suite) : la file passe du plus haut au plus bas. 50 par défaut.",
                },
                "status": {
                    "type": "string",
                    "enum": ["draft", "ready"],
                    "description": "draft (par défaut) ou ready (lancée à la prochaine passe).",
                },
            },
            ("title",),
        ),
    },
    {
        "name": "answer_question",
        "title": "Répondre à une tâche bloquée",
        "scope": WRITE,
        "description": "Répond à une tâche bloquée (« vous attend ») : la réponse est déposée "
        "dans sa discussion, sous la question, comme une réponse donnée depuis la console ou le "
        "téléphone. Pour une question à options numérotées, répondre par le numéro (« 2 ») suffit. "
        "Le runner reprend d'ordinaire de lui-même une tâche dont il attendait la réponse ; "
        "ready=true la remet aussi explicitement en ready (utile quand elle a été bloquée à la "
        "main). Lire d'abord la question avec get_task. Refusé si la tâche n'est pas bloquée.",
        "inputSchema": _schema(
            {
                "task": TASK_REFERENCE,
                "answer": {
                    "type": "string",
                    "description": "La réponse, telle que la personne la donne.",
                },
                "ready": {
                    "type": "boolean",
                    "description": "true : remettre aussi la tâche en ready (false par défaut).",
                },
            },
            ("task", "answer"),
        ),
    },
    {
        "name": "list_solutions",
        "title": "Solutions d'une tâche en attente",
        "scope": READ,
        "description": "Pour une tâche bloquée (« vous attend ») ou en review : pourquoi elle "
        "attend (catégorie — question, accès manquant, action manuelle, crédits, CI, conflit, "
        "découpage —, raison en une phrase, ce qui est déjà fait), ou ce qu'elle a livré (résumé, "
        "pull request, état des checks, points à vérifier), et la liste des solutions proposées, "
        "chacune avec sa clé, son numéro, la colonne où elle envoie la tâche et ce qu'elle "
        "demande (texte, note, modèle, titres). À lire avant apply_solution.",
        "inputSchema": _schema({"task": TASK_REFERENCE}, ("task",)),
    },
    {
        "name": "apply_solution",
        "title": "Appliquer une solution",
        "scope": WRITE,
        "description": "Applique une des solutions que list_solutions propose pour une tâche "
        "bloquée ou en review : la décision et la consigne sont écrites dans sa discussion, que la "
        "prochaine session lira, puis la tâche change de colonne (ready pour la relancer, "
        "validated pour la valider, done pour l'abandonner ou la rejeter). Une tâche remise en "
        "ready sera lancée par le runner à sa prochaine passe, et coûtera une session.",
        "inputSchema": _schema(
            {
                "task": TASK_REFERENCE,
                "solution": {"type": "string", "description": "La clé de la solution (key)."},
                "number": {
                    "type": "integer",
                    "description": "Son numéro (number), pour une option ou un point à vérifier.",
                },
                "text": {
                    "type": "string",
                    "description": "La consigne, la réponse ou la note, quand la solution en demande une.",
                },
                "model": {
                    "type": "string",
                    "description": "Le modèle, pour relancer avec un autre.",
                },
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Les titres des sous-tickets, pour un découpage.",
                },
            },
            ("task", "solution"),
        ),
    },
    {
        "name": "create_idea",
        "title": "Proposer une idée",
        "scope": WRITE,
        "description": "Ajoute une idée aux idées proposées, pour un projet ou pour l'espace de "
        "travail entier : elle n'est pas encore une tâche, elle attend d'être gardée ou jetée "
        "(set_idea_state). Ponos lui donne ensuite son score de pertinence, en arrière-plan. Pour "
        "une tâche à faire tout de suite, utiliser create_task.",
        "inputSchema": _schema(
            {
                "title": {
                    "type": "string",
                    "description": "Ce qu'il faudrait faire, en une ligne.",
                },
                "description": {
                    "type": "string",
                    "description": "Pourquoi cela vaut la peine, en trois lignes au plus.",
                },
                "project": PROJECT_FILTER,
                "kind": {
                    "type": "string",
                    "enum": list(ideas.KINDS),
                    "description": "ticket (par défaut) : une tâche ; project : un nouveau projet "
                    "— seulement sans projet donné.",
                },
                "category": {
                    "type": "string",
                    "enum": list(ideas.CATEGORIES),
                    "description": "ux : l'interface et l'expérience ; feature : une nouvelle "
                    "fonctionnalité ; security : une faille ou un risque ; technical : refacto, "
                    "performance, dette technique.",
                },
            },
            ("title",),
        ),
    },
    {
        "name": "set_idea_state",
        "title": "Garder ou jeter une idée",
        "scope": WRITE,
        "description": "Décide d'une idée : keep (la garder pour plus tard, sans rien créer), "
        "ticket (la transformer en tâche en brouillon, ou en nouveau projet et sa première "
        "tâche), discard (la jeter — elle reste connue et ne sera plus proposée), new (la "
        "remettre parmi les idées proposées ; ce qu'une idée devenue tâche a créé reste sur le "
        "tableau). Rien n'est supprimé.",
        "inputSchema": _schema(
            {
                "idea": {"type": "integer", "description": "L'identifiant de l'idée (list_ideas)."},
                "state": {"type": "string", "enum": ["keep", "ticket", "discard", "new"]},
            },
            ("idea", "state"),
        ),
    },
]

_ANNOTATIONS = {
    READ: {"readOnlyHint": True, "openWorldHint": False},
    WRITE: {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
}


def listed(grant: Grant) -> list[dict]:
    """The tools this client may call — a read-only client is not shown the others."""
    return [
        {
            "name": tool["name"],
            "title": tool["title"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
            "annotations": _ANNOTATIONS[tool["scope"]],
        }
        for tool in TOOLS
        if grant.allows(tool["scope"])
    ]


# -- the protocol -------------------------------------------------------------


def _error(identifier: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def _result(identifier: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def handle(api: Api, grant: Grant, message: Any, address: str = "") -> Any:
    """One JSON-RPC message, or a batch of them: the answer, or None for none.

    `address` is the console's, as the client reached it — what `whoami` says.
    """
    if isinstance(message, list):
        answers = [
            answer for answer in (handle(api, grant, item, address) for item in message) if answer
        ]
        return answers or None
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "not a JSON-RPC 2.0 message")
    method = message.get("method")
    identifier = message.get("id")
    if not isinstance(method, str):
        # A response from the client: this server never asks anything.
        return None
    if "id" not in message:
        return None  # a notification — `initialized`, `cancelled`: nothing to say
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(identifier, -32602, "params is an object")
    if method == "initialize":
        asked = str(params.get("protocolVersion") or "")
        return _result(
            identifier,
            {
                "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "ponos",
                    "title": "Ponos",
                    "version": __version__,
                    "description": DESCRIPTION,
                    "icons": ICONS,
                    "websiteUrl": WEBSITE,
                },
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(identifier, {})
    if method == "tools/list":
        return _result(identifier, {"tools": listed(grant)})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(identifier, -32602, "tools/call takes a name and an arguments object")
        tool = next((tool for tool in TOOLS if tool["name"] == name), None)
        if tool is None:
            return _error(identifier, -32602, f"unknown tool: {name}")
        return _result(identifier, call(api, grant, tool, arguments, address))
    return _error(identifier, -32601, f"method not found: {method}")


def call(api: Api, grant: Grant, tool: dict, arguments: dict, address: str = "") -> dict:
    """One tool, answered as MCP wants it: text for the model, and the same as data.

    A tool that refuses says why in its result, flagged as an error, rather
    than as a protocol error: the model reads it, and can do something about it.
    """
    name = tool["name"]
    writes = tool["scope"] == WRITE
    if not grant.allows(tool["scope"]):
        record(grant, name, arguments, "refused: no write scope")
        return _refusal(
            "Ce client n'a que l'accès en lecture : il ne peut rien créer ni modifier. "
            "Il faut reconnecter le connecteur en cochant l'écriture."
        )
    try:
        if name == "whoami":
            # The one tool about the connection rather than the board: it is
            # told who holds the key, which no other tool needs to know.
            payload = whoami(api, grant, address, **_arguments(tool, arguments))
        else:
            payload = HANDLERS[name](api, **_arguments(tool, arguments))
    except ToolError as error:
        if writes:
            record(grant, name, arguments, f"refused: {error}")
        return _refusal(str(error))
    except (ValueError, LookupError) as error:
        if writes:
            record(grant, name, arguments, f"refused: {error}")
        return _refusal(str(error))
    except store.StoreError as error:
        if writes:
            record(grant, name, arguments, f"failed: {error}")
        return _refusal(f"Le tableau n'a pas répondu : {str(error).splitlines()[0]}")
    except Exception as error:  # a tool fails in its answer, not by killing the request
        logger.exception("mcp: the tool %s failed", name, extra=log.FILE_ONLY)
        if writes:
            record(grant, name, arguments, f"failed: {error}")
        return _refusal(
            f"Erreur : {str(error).splitlines()[0] if str(error) else type(error).__name__}"
        )
    if writes:
        record(grant, name, arguments, "ok")
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}],
        "structuredContent": payload,
        "isError": False,
    }


def _refusal(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _arguments(tool: dict, arguments: dict) -> dict:
    """The arguments a tool declares, checked against its schema's types and enums."""
    schema = tool["inputSchema"]
    properties = schema["properties"]
    unknown = set(arguments) - set(properties)
    if unknown:
        raise ToolError(f"Arguments inconnus : {', '.join(sorted(unknown))}.")
    for name in schema.get("required", ()):
        if arguments.get(name) in (None, ""):
            raise ToolError(f"L'argument « {name} » est obligatoire.")
    kept: dict[str, Any] = {}
    for name, value in arguments.items():
        if value is None:
            continue
        expected = properties[name]
        kind = expected.get("type")
        if kind == "string" and not isinstance(value, str):
            raise ToolError(f"« {name} » est un texte.")
        if kind == "boolean" and not isinstance(value, bool):
            raise ToolError(f"« {name} » vaut true ou false.")
        if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ToolError(f"« {name} » est un nombre entier.")
        if kind == "array" and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            raise ToolError(f"« {name} » est une liste de textes.")
        if "enum" in expected and value not in expected["enum"]:
            raise ToolError(
                f"« {name} » vaut l'une de ces valeurs : {', '.join(expected['enum'])}."
            )
        if kind == "integer":
            low, high = expected.get("minimum"), expected.get("maximum")
            if (low is not None and value < low) or (high is not None and value > high):
                raise ToolError(f"« {name} » est compris entre {low} et {high}.")
        kept[name] = value
    return kept


# -- the journal --------------------------------------------------------------


def record(grant: Grant, tool: str, arguments: dict, outcome: str) -> None:
    """One write asked for: the tool, when, by which client, and how it ended.

    Arguments shortened, not dropped: a task's description can be a page, and
    the journal is read to know who did what — not to keep a second copy.
    """
    kept = {
        key: (
            value[:ARGUMENT_LIMIT] + "…"
            if isinstance(value, str) and len(value) > ARGUMENT_LIMIT
            else value
        )
        for key, value in arguments.items()
    }
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO mcp_calls (at, client, name, tool, arguments, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    grant.client,
                    grant.name,
                    tool,
                    json.dumps(kept, ensure_ascii=False),
                    outcome[:500],
                ),
            )
    except db.ERRORS:
        pass  # a journal that cannot be written costs the line, never the call


def calls(limit: int = 30) -> list[dict]:
    """The last writes asked for, newest first — for `ponos mcp list`."""
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT at, client, name, tool, arguments, outcome FROM mcp_calls ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "at": at,
            "client": client,
            "name": name,
            "tool": tool,
            "arguments": arguments,
            "outcome": outcome,
        }
        for at, client, name, tool, arguments, outcome in rows
    ]


# -- reading ------------------------------------------------------------------


def _bare(reference: str) -> str:
    return reference.replace("-", "").strip().lower()


def _projects(api: Api) -> list[dict]:
    return sorted(api.projects().values(), key=lambda project: project["name"].lower())


def _project(api: Api, reference: str) -> dict:
    """The project a name or an id designates — or a refusal that lists the known ones."""
    wanted = reference.strip()
    for project in _projects(api):
        if _bare(wanted) == project["id"] or wanted.lower() == project["name"].lower():
            return project
    known = ", ".join(project["name"] for project in _projects(api)) or "aucun"
    raise ToolError(f"Aucun projet « {wanted} ». Projets connus : {known}.")


def _icon(project: dict) -> str:
    icon = project.get("icon") or {}
    if icon.get("kind") == "emoji":
        return str(icon.get("emoji") or "")
    return str(icon.get("url") or "")


def _task(card: dict) -> dict:
    """A card of the board, as a task: what any board says, and nothing of Notion's."""
    return {
        "id": card["id"],
        "short": card["short"],
        "title": card["title"] or "(sans titre)",
        "project": card["project"],
        "status": card["column"],
        "waiting_for_you": card["column"] == "blocked",
        "type": card["type"],
        "priority": card["priority"],
        "pull_request": card["pull_request"],
        "cost_usd": card["cost"],
        "scheduled": card["scheduled"],
        "created": card["created"],
        "edited": card["edited"],
    }


def _card(api: Api, reference: str) -> dict:
    """The board's card for a task, found by its long or its short id."""
    wanted = re.sub(r"[^0-9a-f]", "", _bare(reference))
    if not wanted:
        raise ToolError("Donner l'identifiant d'une tâche, tel que list_tasks le renvoie.")
    tickets = api.board()["tickets"]
    found = [card for card in tickets if card["id"] == wanted or card["short"] == wanted]
    if not found and len(wanted) >= 6:
        found = [card for card in tickets if card["id"].startswith(wanted)]
    if not found:
        raise ToolError(f"Aucune tâche « {reference} ».")
    if len(found) > 1:
        raise ToolError(f"« {reference} » désigne plusieurs tâches : donner l'identifiant long.")
    return found[0]


def whoami(api: Api, grant: Grant, address: str = "") -> dict:
    configuration = api.config
    try:
        projects: int | None = len(api.projects())
        waiting: int | None = sum(
            1 for card in api.board()["tickets"] if card["column"] == "blocked"
        )
    except store.StoreError:
        projects = waiting = None  # the board is down; who you are is not
    return {
        "console": address,
        "email": configuration.web.email.strip(),
        "client": grant.name,
        "access": "lecture et écriture" if grant.allows(WRITE) else "lecture seule",
        "scope": "Toutes les tâches, tous les projets et toutes les idées de cette console"
        + ("" if grant.allows(WRITE) else " — en lecture seulement")
        + ".",
        "board": configuration.storage.mode,
        "projects": projects,
        "waiting_for_you": waiting,
        "version": __version__,
    }


def list_projects(api: Api) -> dict:
    return {
        "projects": [
            {
                "id": project["id"],
                "name": project["name"],
                "icon": _icon(project),
                "repository": project.get("repository", ""),
                "kind": project.get("kind", ""),
            }
            for project in _projects(api)
        ]
    }


def list_tasks(
    api: Api,
    project: str = "",
    status: str = "",
    waiting_for_you: bool = False,
    limit: int = LISTED,
) -> dict:
    cards = api.board()["tickets"]
    if project:
        name = _project(api, project)["name"]
        cards = [card for card in cards if card["project"] == name]
    if waiting_for_you:
        cards = [card for card in cards if card["column"] == "blocked"]
    if status:
        cards = [card for card in cards if card["column"] == status]
    cards = sorted(
        cards, key=lambda card: card.get("edited") or card.get("created") or "", reverse=True
    )
    return {"count": len(cards), "tasks": [_task(card) for card in cards[:limit]]}


def get_task(api: Api, task: str) -> dict:
    card = _card(api, task)
    detail = api.ticket(card["id"])
    talk = api.talk(card["id"])
    messages = [
        {
            "from": "ponos" if message["role"] == "runner" else "vous",
            "text": _short(message["text"], MESSAGE_LIMIT),
            "at": message["at"],
        }
        for message in talk["messages"][-MESSAGES:]
    ]
    runs = [
        {
            "started_at": run.get("started_at"),
            "ended_at": run.get("ended_at"),
            "status": run.get("status"),
            "reason": _short(str(run.get("reason") or ""), MESSAGE_LIMIT),
            "cost_usd": run.get("cost_usd"),
            "model": run.get("reported") or run.get("model") or "",
        }
        for run in journal.runs(card["id"], limit=RUNS)
    ]
    return {
        **_task(card),
        "description": _short(detail.get("content") or "", DESCRIPTION_LIMIT),
        "question": messages[-1]["text"] if talk["waiting"] and messages else "",
        "conversation": messages,
        "session": {
            "id": detail.get("session") or "",
            "duration_seconds": detail.get("duration"),
            "model": detail.get("model_in_use") or detail.get("model") or "",
        },
        "runs": runs,
    }


def runner_status(api: Api, days: int = 30) -> dict:
    configuration = api.config
    held = state.running()
    sessions = live.active(held=lambda: held)
    try:
        cards = api.board()["tickets"]
    except store.StoreError:
        cards = []
    by_short = {card["short"]: card for card in cards}
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=days - 1)
    try:
        projects = state.spent_by_project(since)
    except db.ERRORS:
        projects = []
    limit = configuration.budget.daily_usd
    return {
        "timer": "enabled" if config_module.in_container() else systemd.read().label,
        "interval_seconds": configuration.runner.interval_seconds,
        "run_in_progress": bool(held),
        "sessions": [
            {
                "task": session["source"],
                "title": (by_short.get(session["source"]) or {}).get("title", ""),
            }
            for session in sessions
        ],
        "running_tasks": [_task(card) for card in cards if card["column"] == "running"],
        "spend": {
            "today_usd": round(state.spent_today(), 2),
            "daily_limit_usd": limit or None,
            "period_days": days,
            "since": since.date().isoformat(),
            "period_usd": round(sum(cost for _, _, cost in projects), 2),
            "by_project": [
                {"project": name or "(sans projet)", "sessions": count, "cost_usd": round(cost, 2)}
                for name, count, cost in projects
            ],
        },
    }


def list_ideas(api: Api, project: str = "", status: str = "proposed") -> dict:
    scope = _project(api, project)["id"] if project else ""
    return {
        "scope": "project" if scope else "workspace",
        "ideas": [_idea(idea.shown()) for idea in ideas.listed(scope, (status,))],
    }


def _idea(shown: dict) -> dict:
    return {
        "id": shown["id"],
        "title": shown["title"],
        "description": shown["description"],
        "kind": shown["kind"],
        "category": shown["category"],
        "score": shown["score"],
        "score_reason": shown["score_reason"],
        "status": shown["status"],
        "task": shown["ticket"],
        "created_at": shown["created_at"],
        "decided_at": shown["decided_at"],
    }


# -- writing ------------------------------------------------------------------


def create_task(
    api: Api,
    title: str,
    description: str = "",
    project: str = "",
    type: str = "",  # noqa: A002 — the name the tool gives it
    priority: int | str = "",
    status: str = "draft",
) -> dict:
    if not title.strip():
        raise ToolError("Une tâche a besoin d'un titre.")
    chosen = _project(api, project) if project else None
    created = api.create_ticket(
        title,
        description,
        chosen["id"] if chosen else "",
        ready=status == "ready",
        priority=priority,
        kind=type,
    )
    return {
        "id": created["id"].replace("-", ""),
        "title": created["title"],
        "project": chosen["name"] if chosen else "",
        "status": status,
    }


def answer_question(api: Api, task: str, answer: str, ready: bool = False) -> dict:
    card = _card(api, task)
    if card["column"] != "blocked":
        raise ToolError(
            f"La tâche « {card['title']} » n'attend pas de réponse (statut {card['column']}) : "
            "seule une tâche bloquée peut recevoir une réponse."
        )
    if not answer.strip():
        raise ToolError("La réponse est vide.")
    api.tell(card["id"], answer)
    moved = ""
    if ready:
        moved = api.set_status(card["id"], "ready", card["status"])["status"]
    return {
        "id": card["id"],
        "title": card["title"],
        "answered": True,
        "status": "ready" if moved else "blocked",
    }


def list_solutions(api: Api, task: str) -> dict:
    card = _card(api, task)
    if card["column"] not in ("blocked", "review"):
        raise ToolError(
            f"La tâche « {card['title']} » n'attend aucune décision (statut {card['column']}) : "
            "seules une tâche bloquée et une tâche en review en proposent."
        )
    return {"title": card["title"], **api.decision(card["id"])}


def apply_solution(
    api: Api,
    task: str,
    solution: str,
    number: int = 0,
    text: str = "",
    model: str = "",
    titles: list[str] | None = None,
) -> dict:
    card = _card(api, task)
    if card["column"] not in ("blocked", "review"):
        raise ToolError(
            f"La tâche « {card['title']} » n'attend aucune décision (statut {card['column']})."
        )
    done = api.decide(
        card["id"],
        solution,
        number=number,
        text=text,
        model=model,
        titles=titles or [],
        channel="MCP",
    )
    return {"id": card["id"], "title": card["title"], **done}


def create_idea(
    api: Api,
    title: str,
    description: str = "",
    project: str = "",
    kind: str = "ticket",
    category: str = "",
) -> dict:
    scope = _project(api, project)["id"] if project else ""
    return _idea(api.ideas.write(scope, kind, title, description, category))


def set_idea_state(api: Api, idea: int, state: str) -> dict:
    if state == "keep":
        return _idea(api.ideas.keep(idea))
    if state == "ticket":
        return _idea(api.ideas.ticket(idea))
    if state == "discard":
        return _idea(api.ideas.discard(idea))
    return _idea(api.ideas.reopen(idea))


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


HANDLERS: dict[str, Callable[..., dict]] = {
    "whoami": whoami,
    "list_projects": list_projects,
    "list_tasks": list_tasks,
    "get_task": get_task,
    "runner_status": runner_status,
    "list_ideas": list_ideas,
    "create_task": create_task,
    "answer_question": answer_question,
    "list_solutions": list_solutions,
    "apply_solution": apply_solution,
    "create_idea": create_idea,
    "set_idea_state": set_idea_state,
}
