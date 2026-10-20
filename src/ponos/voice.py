"""What the runner says on a ticket, and the language it says it in.

Three kinds of text come out of a run, and only one of them is written here.
The **work** — a summary, a document, an answer in a thread — is written by the
session, and `prompt.py` is where it is told which language to write it in. The
**journal** on the terminal is written for whoever is watching a terminal, and
that person is standing in front of the machine. What is left is what the runner
says *on the ticket*: the report under a finished one, the question a blocked
one asks, the line that reaches a phone. That is this module.

Two decisions hold it together.

- **A language is a setting, and English is what it falls back on.**
  `runner.language` names it; a locale, a language written out in full, a
  capitalised code all read down to one of the two spoken here, and anything
  unrecognised is English rather than a failure — a typo in a language name is
  not a reason for a ticket to come back unreported. An empty setting is the
  runner as it always was, and that is the point of it being empty.
- **The first line of a comment is a notification.** Notion pushes a comment to
  the phone as it stands, cut after two or three lines, so the first line is all
  there is: it gets a mark, the verdict as an action — *to review*, *stuck* —
  and the figures that place it, and nothing else. One sentence follows, cut at
  `BRIEF` characters, then a link if there is one. What used to be under that —
  the host that wrote it, the session id, the log path — is not lost, it is read
  off the board's own columns and off the folded block the run leaves on the
  page, which is where somebody looks on the rare day a run went wrong.

Nothing the runner writes where you read it is spelled anywhere else — not the
body of the pull requests it opens, not the note about a branch a ticket already
had, not the answer it relays from your phone. `git.py` hands back facts and the
run says them here, so that a module about git never has to learn that there is
such a thing as a language. What stays English is the journal and the CLI, and
what a session is told: those are read in front of the machine, or by a model.
And an error is quoted as it came — git's, Notion's, or the diagnosis of a
project nobody could find, which `ponos projects` prints word for word:
the sentence around it is translated, the evidence is not.

Adding a language is adding a column to `_SAID`. The keys stay English, because
the code that calls them is English, and a key nobody translated shows up as a
`KeyError` the first time it is said rather than as a sentence in the wrong
language six months later.
"""

from __future__ import annotations

import re

from . import legacy

# The two the runner speaks. English is less a default than the language the
# tool was written in: everything it says was written there first.
LANGUAGES = ("en", "fr")
DEFAULT = "en"

# What a configuration file may reasonably say for each of them.
_SPELLINGS = {
    "en": ("en", "eng", "english", "anglais"),
    "fr": ("fr", "fra", "fre", "french", "français", "francais"),
}


# How long a sentence may be under a verdict. Two hundred characters is about
# what a phone shows before it gives up, and the prompt asks for one sentence:
# this is what happens when it is answered with three.
BRIEF = 200

# What a desktop notification has room for, which is much less than a phone:
# a title the desktop cuts on one line, and a body it shows two or three lines
# of — so two, the second one cut here rather than by the desktop.
TITLE = 60
GIST = 120

# The mark every report opens with, one per verdict. It is read by a person at a
# glance — green is nothing to do, the hand is a question — and by the runner, as
# the thing that tells its own comment from your answer: see `is_report`.
MARKS = {
    "review": "✅",
    "read": "✅",
    "merged": "✅",
    "published": "✅",
    "prepared": "✅",
    "classified": "🏷️",
    "chosen": "🧠",
    "blocked": "🙋",
    "failed": "⚠️",
    "waiting": "⏸️",
    "requeued": "↩️",
}

# How every report opened until the marks arrived: `<old name>@<host> — `.
# Still recognised, and only recognised — nothing writes it any more. A board
# does not start over when the runner is updated, and the comments already on it
# have to keep being read as ours. A migration filet too: those reports were
# signed with the name Ponos had before the rename.
SIGNATURE = f"{legacy.OLD}@"


def is_report(text: str) -> bool:
    """Was this comment written by a run, rather than by a person?

    The honest answer is `conversation.ours`, which asks Notion who wrote it.
    This is the fallback for the boards where Notion will not say — an
    integration without *Read user information* — and it reads the only thing a
    report has that an answer does not: the mark it opens with.
    """
    said = str(text or "").lstrip()
    return said.startswith(tuple(MARKS.values())) or said.startswith(SIGNATURE)


def plain(text: str) -> str:
    """A report without the host an older run signed it with.

    Reports made before the marks open with `<old name>@laptop — done.`, and
    the host is exactly the part nobody needs — least of all the session about
    to read the thread back as context.
    """
    first, newline, rest = str(text or "").partition("\n")
    if first.lstrip().startswith(SIGNATURE):
        first = first.split("—", 1)[-1].strip()
    return first + newline + rest


def line(error: object) -> str:
    """The first line of an error, which is the part meant for a human."""
    return str(error).splitlines()[0] if str(error).strip() else ""


def _bare(text: object) -> str:
    """Text without what only a comment can draw: links, addresses, Markdown.

    A link keeps its words and loses its address; an address on its own goes
    altogether, since nobody can click it from where it is shown.
    """
    said = str(text or "")
    said = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", said)
    said = re.sub(r"<?\b(?:https?://|www\.)\S+", "", said)
    said = re.sub(r"(?m)^\s*(?:#{1,6}|>|[-*+]|\d+\.)\s+", "", said)
    said = re.sub(r"(\*\*|__|~~)(.+?)\1", r"\2", said)
    said = re.sub(r"(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])", r"\1", said)
    said = re.sub(r"(?<!\w)_(\S(?:.*?\S)?)_(?!\w)", r"\1", said)
    said = said.replace("`", "")
    said = " ".join(said.split())
    return re.sub(r"\s+([,.)])", r"\1", said).strip(" ·—-:")


def _escaped(text: str) -> str:
    """Safe from a desktop that reads a notification's body as markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _project_and_title(title: str, project: str = "") -> tuple[str, str]:
    """A ticket's project and its title, without the one repeated in the other.

    Tickets are often named “Leadz — Fix the form”, which a notification that
    already names the project would say twice. The prefix is dropped when it is
    the project; with no project to compare it to, a short one is taken for it.
    """
    title = " ".join(str(title or "").split())
    found = re.match(r"(.+?)\s+[—–-]\s+(.+)", title) or re.match(r"([^:]+?):\s+(.+)", title)
    if found:
        head, rest = found.group(1).strip(), found.group(2).strip()
        if project and head.casefold() == project.strip().casefold():
            return project.strip(), rest
        if not project and len(head) <= 30 and len(head.split()) <= 3 and "[" not in head:
            return head, rest
    return project.strip(), title


_DESKTOP_EVENT = {
    "blocked": "blocked",
    "failed": "failed",
    "prepared": "prepared",
    "review": "review",
    "merged": "done",
    "published": "done",
}
_DESKTOP_NEXT = ("blocked", "failed", "review", "read", "merged", "published", "prepared")


def _wanted(raw: str) -> str:
    return str(raw or "").strip().lower().replace("_", "-").split("-")[0]


def known(raw: str) -> bool:
    """Does the file name one of the two — rather than something read as English?"""
    return any(_wanted(raw) in spellings for spellings in _SPELLINGS.values())


def understood(raw: str) -> str:
    """The language a file asked for, as one of the two this speaks.

    `fr`, `FR`, `fr-FR`, `french`, `Français` all mean the same thing, and so
    does the region nobody meant to specify: only what comes before the dash is
    read. Anything else is English — see the module's second paragraph.
    """
    wanted = _wanted(raw)
    for language, spellings in _SPELLINGS.items():
        if wanted in spellings:
            return language
    return DEFAULT


# One entry per thing the runner has to say, in every language it says it in.
# Grouped as a run goes: the verdict a report opens with, the facts that place
# it, what a failure is called, and what reaches a phone.
_SAID: dict[str, dict[str, str]] = {
    # -- the verdict, which is the notification -------------------------------
    # One word each, and each one says what is expected *of you*: “done” was
    # true and useless, since it left the reader to work out whether anything
    # was being asked. Every one of these is preceded by its mark — see `MARKS`
    # — and followed by the figures that place it.
    "verdict-review": {"en": "To review", "fr": "À relire"},
    "verdict-read": {"en": "To read", "fr": "À lire"},
    "verdict-merged": {"en": "Merged", "fr": "Fusionnée"},
    "verdict-published": {"en": "Published", "fr": "Publié"},
    "verdict-prepared": {"en": "To validate", "fr": "À valider"},
    "verdict-classified": {"en": "Classified", "fr": "Classé"},
    "verdict-chosen": {
        "en": "Model chosen automatically",
        "fr": "Modèle choisi automatiquement",
    },
    "verdict-blocked": {"en": "Stuck", "fr": "Bloqué"},
    "verdict-failed": {"en": "Failed", "fr": "Échec"},
    "verdict-waiting": {"en": "Waiting", "fr": "En attente"},
    "verdict-requeued": {"en": "Back in the queue", "fr": "Remis dans la file"},
    # -- the facts that go on the same line -----------------------------------
    # Short enough to be read in a row, and in the order somebody reads them:
    # where the work is, how much of it there is, what it took.
    "pull-request": {"en": "PR #{number}", "fr": "PR #{number}"},
    "on-branch": {"en": "branch `{branch}`", "fr": "branche `{branch}`"},
    "in-the-page": {"en": "answer in the page", "fr": "réponse dans la page"},
    "nothing-published": {"en": "nothing published", "fr": "rien de publié"},
    # A ticket that was not code, whose session opened a pull request anyway.
    "pull-request-adopted": {
        "en": "The session opened a pull request itself, outside Ponos's road: {url} — "
        "attached to the ticket, which waits in review rather than done. Validate it to merge.",
        "fr": "La session a ouvert elle-même une pull request, hors du circuit de Ponos : {url} — "
        "rattachée au ticket, qui attend en review plutôt que d'aller en done. Valide-le pour la fusionner.",
    },
    "pull-requests-also": {
        "en": "It opened others too: {urls}.",
        "fr": "Elle en a ouvert d'autres : {urls}.",
    },
    "confidence": {"en": "{level} confidence", "fr": "confiance {level}"},
    "confidence-low": {"en": "low", "fr": "faible"},
    "confidence-medium": {"en": "medium", "fr": "moyenne"},
    "confidence-high": {"en": "high", "fr": "élevée"},
    "merged-with": {"en": "{method} merge", "fr": "fusion en {method}"},
    "merged-before": {"en": "already merged", "fr": "déjà fusionnée"},
    "forced-validation": {
        "en": "Validated automatically (Force validated: {kind}) — {source}",
        "fr": "Validation automatique (Force validated : {kind}) — {source}",
    },
    # Whose decision that was: a project may hold its own automatic validation,
    # and a report that only said "validated" would leave you guessing which
    # switch to turn off. See project_settings.py.
    "forced-by-project": {"en": "the project's setting", "fr": "réglage du projet"},
    "forced-by-global": {"en": "the global setting", "fr": "réglage global"},
    "credits-out": {
        "en": "out of credit, back in “{status}” until {when}",
        "fr": "crédits épuisés, retour dans « {status} » jusqu'à {when}",
    },
    "abandoned": {
        "en": "nobody was working on it any more, {minutes} after the last trace",
        "fr": "plus personne ne s'en occupait, {minutes} après la dernière trace",
    },
    # -- the one sentence under a verdict -------------------------------------
    # What follows a yes-no question, on its own line: the two words that
    # answer it. Recognised too, in every language — see `question.found`.
    "yes-or-no": {"en": "yes / no", "fr": "oui / non"},
    # What a ticket stopped on, in front of why — see question.CATEGORIES. Read
    # back by the console, in every language, to offer what fits: decisions.py.
    "category-question": {"en": "A decision to make", "fr": "Une décision à prendre"},
    "category-access": {"en": "Missing access", "fr": "Accès manquant"},
    "category-manual": {"en": "Something to do by hand", "fr": "Action manuelle requise"},
    "category-credits": {"en": "Out of credit", "fr": "Crédits épuisés"},
    "category-ci": {"en": "Failing checks", "fr": "CI en échec"},
    "category-conflict": {"en": "Conflict", "fr": "Conflit"},
    "category-split": {"en": "Too big for one ticket", "fr": "Trop gros pour un ticket"},
    "category-other": {"en": "Stuck", "fr": "Bloqué"},
    "because": {"en": "{category}: {why}", "fr": "{category} : {why}"},
    # A line of a review report: what the session could not check itself.
    "caveat": {"en": "To check: {text}", "fr": "À vérifier : {text}"},
    "trace-in-page": {
        "en": "What it did is in the folded block at the bottom of the page.",
        "fr": "Ce qu'il a fait est dans le bloc replié en bas de la page.",
    },
    "trace": {
        "en": "To pick the session back up: `{resume}`{picker}. Its log is `{log}`.",
        "fr": "Pour reprendre la session : `{resume}`{picker}. Son journal est `{log}`.",
    },
    "trace-picker": {
        "en": ", or from `claude` in `{home}`",
        "fr": ", ou depuis `claude` dans `{home}`",
    },
    "kind-settled": {
        "en": "It could have been {other}: I took {kind}, which asks for no commit — its "
        "report is what it delivers.",
        "fr": "Ça aurait pu être {other} : j'ai pris {kind}, qui n'exige pas de commit — "
        "son compte rendu est son livrable.",
    },
    "classified-fix": {
        "en": "Wrong? Change the {property} column — a type somebody chose is never overwritten.",
        "fr": "C'est faux ? Change la colonne {property} — un type choisi à la main "
        "n'est jamais écrasé.",
    },
    # A code ticket's sub-type, when the runner filled it — see subtypes.py.
    # Notes of the report: the column says the sub-type, these say who chose it.
    "subtype-prefix": {
        "en": "Sub-type {subtype}, read from the title's prefix.",
        "fr": "Sous-type {subtype}, lu dans le préfixe du titre.",
    },
    "subtype-guessed": {
        "en": "Sub-type {subtype}, deduced from the ticket ({level} confidence): {reason}",
        "fr": "Sous-type {subtype}, déduit du ticket (confiance {level}) : {reason}",
    },
    "subtype-doubt": {
        "en": "Sub-type {subtype} by default: the runner could not tell which one it "
        "was. Change the {property} column if it is another.",
        "fr": "Sous-type {subtype} par défaut : le runner n'a pas su dire lequel c'était. "
        "Change la colonne {property} si c'en est un autre.",
    },
    # Why a model was chosen, one signal each, joined into one sentence — see
    # models.py for the rules they name.
    "model-type": {"en": "{kind} ticket", "fr": "ticket {kind}"},
    "model-subtype-lower": {
        "en": "{subtype}: one level lower",
        "fr": "{subtype} : un niveau plus bas",
    },
    "model-subtype-higher": {
        "en": "{subtype}: one level higher",
        "fr": "{subtype} : un niveau plus haut",
    },
    "model-small": {
        "en": "small targeted change ({words})",
        "fr": "petite modification ciblée ({words})",
    },
    "model-short": {"en": "short request", "fr": "demande courte"},
    "model-ordinary": {"en": "request of ordinary size", "fr": "demande de taille ordinaire"},
    "model-long": {
        "en": "long request ({count} words, {steps} steps)",
        "fr": "demande longue ({count} mots, {steps} étapes)",
    },
    "model-heavy": {"en": "heavy work ({words})", "fr": "travail lourd ({words})"},
    "model-urgent": {
        "en": "priority {priority}, not the lightest model",
        "fr": "priorité {priority}, pas le modèle le plus léger",
    },
    "model-escalated": {
        "en": "one level up after a failed run on {model}",
        "fr": "un cran au-dessus après un échec sur {model}",
    },
    "model-kept": {
        "en": "kept since the escalation to {model}, which happens only once",
        "fr": "gardé depuis l'escalade vers {model}, qui n'a lieu qu'une fois",
    },
    "fable-refused": {
        "en": "Fable is turned off in the settings: run on Opus.",
        "fr": "Fable désactivé dans les réglages : lancé sur Opus.",
    },
    "model-resumed": {
        "en": "the model the interrupted session began on",
        "fr": "le modèle sur lequel la session interrompue avait commencé",
    },
    "prepared-next": {
        "en": "Move it to {validated} and it goes out as it stands; until then, nothing "
        "has left this machine.",
        "fr": "Passe-le en {validated} et il part tel quel ; d'ici là, rien n'a quitté "
        "cette machine.",
    },
    # -- a ticket that did not ------------------------------------------------
    "kind-unknown": {
        "en": "I could not tell what kind of ticket this is",
        "fr": "je n'ai pas su dire de quel type est ce ticket",
    },
    "kind-unsure": {
        "en": "I am not sure what kind of ticket this is",
        "fr": "je ne suis pas sûr du type de ce ticket",
    },
    "kind-hesitant": {
        "en": "I hesitate between two types, and one of them acts on the world",
        "fr": "j'hésite entre deux types, et l'un d'eux agit sur le monde",
    },
    "kind-question": {
        "en": "Which type is it — {choices}? Choose it in the {property} column; nothing "
        "runs until then.",
        "fr": "De quel type est-il — {choices} ? Choisis-le dans la colonne {property} ; "
        "rien ne s'exécute d'ici là.",
    },
    "kind-question-between": {
        "en": "{first} or {second}? Choose it in the {property} column; nothing runs until "
        "then. In doubt, I would take {prudent}.",
        "fr": "{first} ou {second} ? Choisis-le dans la colonne {property} ; rien ne "
        "s'exécute d'ici là. Dans le doute, je retiendrais {prudent}.",
    },
    "no-project": {
        "en": "I could not find its project on this machine",
        "fr": "je n'ai pas trouvé son projet sur cette machine",
    },
    "project-deleted": {
        "en": "Blocked: its project, “{project}”, was deleted from the console, so nothing "
        "will run on this ticket. Move it back to ready once it points at another project.",
        "fr": "Bloqué : son projet, « {project} », a été supprimé depuis la console, donc rien "
        "ne sera exécuté sur ce ticket. Remets-le en prêt une fois relié à un autre projet.",
    },
    # Why the console's “New project” refuses one. Said under the field it is
    # about, in the runner's language, like everything else it writes back.
    "project-no-database": {
        "en": "This workspace has no projects database to create it in.",
        "fr": "Cet espace de travail n'a pas de base de projets où le créer.",
    },
    "project-needs-name": {
        "en": "A project needs a name.",
        "fr": "Un projet a besoin d'un nom.",
    },
    "project-name-taken": {
        "en": "A project is already called “{name}”.",
        "fr": "Un projet s'appelle déjà « {name} ».",
    },
    "project-needs-repository": {
        "en": "A code project needs a repository: a GitHub address, or a folder on this machine.",
        "fr": "Un projet de code a besoin d'un dépôt : une adresse GitHub, ou un dossier sur cette machine.",
    },
    "project-github-invalid": {
        "en": "“{given}” is not a GitHub repository: write owner/repo, or its github.com address.",
        "fr": "« {given} » n'est pas un dépôt GitHub : écris owner/repo, ou son adresse github.com.",
    },
    "project-path-relative": {
        "en": "Write the whole path, from / or from ~.",
        "fr": "Écris le chemin en entier, depuis / ou depuis ~.",
    },
    "project-path-missing": {
        "en": "There is no folder at {path} on this machine.",
        "fr": "Il n'y a pas de dossier à {path} sur cette machine.",
    },
    "project-path-not-git": {
        "en": "{path} is not a git repository.",
        "fr": "{path} n'est pas un dépôt git.",
    },
    "project-site-invalid": {
        "en": "“{given}” is not a web address: it starts with https://.",
        "fr": "« {given} » n'est pas une adresse web : elle commence par https://.",
    },
    "unreadable": {
        "en": "I could not read what the ticket says",
        "fr": "je n'ai pas réussi à lire ce que dit le ticket",
    },
    "empty-ticket": {
        "en": "there is nothing here to work from — no title, and no description",
        "fr": "il n'y a rien pour commencer — ni titre, ni description",
    },
    "empty-ticket-detail": {
        "en": "A title, or the template's headings filled in, and back to the ready column.",
        "fr": "Un titre, ou les rubriques du modèle remplies, et retour dans la colonne prête.",
    },
    "no-session": {
        "en": "the Claude session would not start",
        "fr": "la session Claude n'a pas voulu démarrer",
    },
    "crashed": {
        "en": "the runner itself broke while handling this ticket",
        "fr": "le runner lui-même a cassé en traitant ce ticket",
    },
    "no-worktree": {
        "en": "I could not make the worktree to work in",
        "fr": "je n'ai pas pu créer le worktree pour travailler",
    },
    "asked-something": {
        "en": "the session stopped to ask you something",
        "fr": "la session s'est arrêtée pour poser une question",
    },
    "over-ticket-budget": {
        "en": "the session reached the ticket's spending limit ({limit})",
        "fr": "la session a atteint le plafond de dépense du ticket ({limit})",
    },
    "over-ticket-budget-detail": {
        "en": "Raise `budget.per_ticket_usd` or split the ticket, then answer here to carry on.",
        "fr": "Relève `budget.per_ticket_usd` ou découpe le ticket, puis réponds ici pour reprendre.",
    },
    "session-failed": {
        "en": "the session did not make it to the end",
        "fr": "la session n'est pas allée au bout",
    },
    # A session ended by something other than itself — see Execution._died.
    "session-killed": {
        "en": "the session was cut short from outside and could not be carried through",
        "fr": "la session a été interrompue de l'extérieur et n'a pas pu aller au bout",
    },
    "session-killed-detail": {
        "en": "Cause: {why}. One more try was made once the network answered.",
        "fr": "Cause : {why}. Une reprise a été tentée dès que le réseau répondait.",
    },
    "session-killed-question": {
        "en": "Put the ticket back in Ready to run it again?",
        "fr": "Remettre le ticket en Prêt pour le relancer ?",
    },
    "killed-signal": {"en": "signal {signal}", "fr": "signal {signal}"},
    "killed-oom": {
        "en": "the machine ran out of memory ({line})",
        "fr": "la machine a manqué de mémoire ({line})",
    },
    "killed-network": {
        "en": "the network was unreachable",
        "fr": "le réseau était injoignable",
    },
    "memory-short": {
        "en": "Only {free} MB of memory available (under {minimum} MB): no session is started until it comes back.",
        "fr": "Seulement {free} Mo de mémoire disponibles (sous {minimum} Mo) : aucune session ne démarre avant son retour.",
    },
    "disk-short": {
        "en": "Only {free} MB free on the disk (under {minimum} MB), even after a tidy: no ticket is started until room is back.",
        "fr": "Seulement {free} Mo libres sur le disque (sous {minimum} Mo), même après un nettoyage : aucun ticket ne démarre avant que la place revienne.",
    },
    "no-answer": {
        "en": "the session stopped without writing an answer",
        "fr": "la session s'est arrêtée sans écrire de réponse",
    },
    "no-answer-detail": {
        "en": "{summary}\n\nNothing was written to ANSWER.md.",
        "fr": "{summary}\n\nRien n'a été écrit dans ANSWER.md.",
    },
    "nothing-committed": {
        "en": "the session called itself done without committing anything",
        "fr": "la session s'est déclarée terminée sans un seul commit",
    },
    "done-elsewhere": {
        "en": "Nothing committed: the work was done outside the repository, and its report "
        "is in the page.",
        "fr": "Aucun commit : le travail a été fait hors du dépôt, et son compte rendu est "
        "dans la page.",
    },
    "push-refused": {
        "en": "the commits are there, but pushing them was refused",
        "fr": "les commits sont là, mais leur push a été refusé",
    },
    "push-refused-detail": {
        "en": "The branch `{branch}` is kept here, so nothing is lost.",
        "fr": "La branche `{branch}` est conservée ici, donc rien n'est perdu.",
    },
    "answer-not-written": {
        "en": "I could not write the answer into the ticket",
        "fr": "je n'ai pas pu écrire la réponse dans le ticket",
    },
    "answer-on-disk": {
        "en": "It is still on disk, at `{path}`.",
        "fr": "Elle est toujours sur le disque, dans `{path}`.",
    },
    "not-published": {
        "en": "it was validated, but publishing it did not work",
        "fr": "il a été validé, mais la publication n'a pas fonctionné",
    },
    "pull-request-closed": {
        "en": "it was validated, but its pull request was closed rather than merged",
        "fr": "il a été validé, mais sa pull request a été fermée au lieu d'être fusionnée",
    },
    "pull-request-closed-detail": {
        "en": "{url}\n\nReopen it, or bring the ticket back to the ready column.",
        "fr": "{url}\n\nÀ rouvrir, ou à ramener le ticket dans la colonne prête.",
    },
    "pull-request-closed-question": {
        "en": "Its pull request was closed rather than merged: {url}",
        "fr": "Sa pull request a été fermée au lieu d'être fusionnée : {url}",
    },
    "merge-refused": {
        "en": "the pull request would not merge",
        "fr": "la pull request n'a pas voulu fusionner",
    },
    "merge-rebased": {
        "en": (
            "The merge was refused for being behind, so `{branch}` was replayed onto "
            "`{base}` and pushed again."
        ),
        "fr": (
            "La fusion a été refusée parce que la branche était en retard : `{branch}` a "
            "été rejouée sur `{base}` puis repoussée."
        ),
    },
    "forced-postponed": {
        "en": "The credit reserve is reached: it goes out on the first pass that has credit again.",
        "fr": "La réserve de crédits est atteinte : il part au premier passage qui en a de nouveau.",
    },
    "forced-merge-refused": {
        "en": "Not merged, left in review: {error}",
        "fr": "Pas fusionnée, laissée en relecture : {error}",
    },
    "forced-merge-postponed": {
        "en": "Merge postponed to the next pass, left validated: {reason}",
        "fr": "Fusion reportée au passage suivant, laissée validée : {reason}",
    },
    "forced-behind": {
        "en": "its branch is behind its base",
        "fr": "sa branche est en retard sur sa base",
    },
    "forced-conflicting": {
        "en": "its branch conflicts with its base",
        "fr": "sa branche est en conflit avec sa base",
    },
    "forced-checks-red": {
        "en": "its checks fail",
        "fr": "ses vérifications échouent",
    },
    "merge-refused-question": {
        "en": "GitHub refused the merge: {error}",
        "fr": "GitHub a refusé la fusion : {error}",
    },
    "rebased-too-often": {
        "en": "`{base}` keeps moving faster than its pull request can be replayed onto it",
        "fr": "`{base}` avance plus vite que sa pull request ne peut être rejouée dessus",
    },
    "rebased-too-often-question": {
        "en": (
            "Its branch was replayed onto `{base}` {count} times and still does not merge, "
            "because `{base}` moves in between. Merge it by hand, or move it back to "
            "validated for another try?"
        ),
        "fr": (
            "Sa branche a été rejouée {count} fois sur `{base}` et ne fusionne toujours "
            "pas, parce que `{base}` bouge entre-temps. La fusionner à la main, ou la "
            "remettre en validé pour un nouvel essai ?"
        ),
    },
    # -- a validated merge whose conflicts a session resolved ------------------
    "conflict-facts": {
        "en": "`{branch}` replayed onto `{base}` at `{onto}` — in conflict: {files}.",
        "fr": "`{branch}` rejouée sur `{base}` à `{onto}` — en conflit : {files}.",
    },
    "conflict-none": {"en": "nothing, in the end", "fr": "rien, finalement"},
    "conflicts-resolved": {"en": "conflicts resolved", "fr": "conflits résolus"},
    "conflict-open": {
        "en": "its pull request conflicts with `{base}`, and the conflict needs a decision",
        "fr": "sa pull request est en conflit avec `{base}`, et le conflit demande une décision",
    },
    "conflict-unfinished": {
        "en": "the conflicts were not fully resolved",
        "fr": "les conflits n'ont pas été entièrement résolus",
    },
    "conflict-unfinished-question": {
        "en": "The session said it had resolved the conflicts, but {problem}. Nothing was pushed.",
        "fr": "La session dit avoir résolu les conflits, mais {problem}. Rien n'a été poussé.",
    },
    "unfinished-rebase": {
        "en": "the rebase was left in progress",
        "fr": "le rebase est resté en cours",
    },
    "unfinished-markers": {
        "en": "conflict markers are still in {files}",
        "fr": "des marqueurs de conflit restent dans {files}",
    },
    "unfinished-base": {
        "en": "the branch is not on top of `{base}`",
        "fr": "la branche n'est pas au-dessus de `{base}`",
    },
    "unfinished-dirty": {
        "en": "changes were left uncommitted",
        "fr": "des modifications n'ont pas été commitées",
    },
    "conflict-aside": {
        "en": "The branch as far as it got is pushed on its own, as `{branch}`.",
        "fr": "La branche, telle qu'elle en est, est poussée à part, sous `{branch}`.",
    },
    "pushed-over": {
        "en": "somebody pushed to `{branch}` since the runner last did",
        "fr": "quelqu'un a poussé sur `{branch}` depuis le dernier passage du runner",
    },
    "pushed-over-question": {
        "en": (
            "Commits were pushed to `{branch}` by someone else while its conflicts were "
            "being resolved. They were not overwritten: which of the two should win?"
        ),
        "fr": (
            "Quelqu'un a poussé des commits sur `{branch}` pendant la résolution de ses "
            "conflits. Ils n'ont pas été écrasés : laquelle des deux doit l'emporter ?"
        ),
    },
    "checks-red": {
        "en": "its conflicts were resolved, but its checks fail",
        "fr": "ses conflits ont été résolus, mais ses vérifications échouent",
    },
    "checks-red-question": {
        "en": "The resolution is pushed, and the pull request's checks fail on it: {url}",
        "fr": "La résolution est poussée, et les vérifications de la pull request échouent : {url}",
    },
    "repair-fixed": {
        "en": "A session repaired the red checks ({names}) and pushed the fix.",
        "fr": "Une session a réparé les vérifications rouges ({names}) et poussé le correctif.",
    },
    "repair-still-red": {
        "en": "The repair was pushed, and the checks are still red.",
        "fr": "Le correctif est poussé, et les vérifications sont toujours rouges.",
    },
    "repair-blocked": {
        "en": "A session looked at the red checks ({names}) and could not repair them.",
        "fr": "Une session a examiné les vérifications rouges ({names}) sans pouvoir les réparer.",
    },
    "repair-nothing": {
        "en": "A session looked at the red checks ({names}) and committed nothing.",
        "fr": "Une session a examiné les vérifications rouges ({names}) sans rien valider.",
    },
    "repair-unfinished": {
        "en": "The repairing session left its worktree unfinished, nothing was pushed.",
        "fr": "La session de réparation a laissé son worktree inachevé, rien n'est poussé.",
    },
    "repair-push-refused": {
        "en": "The repair could not be pushed: {error}",
        "fr": "Le correctif n'a pas pu être poussé : {error}",
    },
    "checks-passed": {"en": "CI: green.", "fr": "CI : verte."},
    "checks-failed": {"en": "CI: red.", "fr": "CI : rouge."},
    "checks-flaky": {
        "en": "CI: red on {names}, green once run again — a flaky test, not this pull request.",
        "fr": "CI : rouge sur {names}, verte une fois relancée — un test instable, pas cette pull request.",
    },
    "checks-base-red": {
        "en": (
            "CI: red on {names}, which `{base}` fails too — the base is red, this pull "
            "request is not to blame."
        ),
        "fr": (
            "CI : rouge sur {names}, que `{base}` échoue aussi — la base est rouge, "
            "cette pull request n'y est pour rien."
        ),
    },
    "base-red": {
        "en": "the base is red, it is not this pull request",
        "fr": "la base est rouge, ce n'est pas cette PR",
    },
    "base-red-held": {
        "en": (
            "Left aside until `{base}` is green again, then replayed on its own: no session "
            "is started for it. Repair ticket: {repair}."
        ),
        "fr": (
            "Mise de côté jusqu'à ce que `{base}` redevienne verte, puis rejouée toute seule : "
            "aucune session n'est lancée pour elle. Ticket de réparation : {repair}."
        ),
    },
    "base-green-again": {
        "en": "`{base}` is green again — the pull request is replayed.",
        "fr": "`{base}` est de nouveau verte — la pull request est rejouée.",
    },
    "forced-base-red": {
        "en": "the base is red, it is not this pull request",
        "fr": "la base est rouge, ce n'est pas cette PR",
    },
    "repair-title": {"en": "Repair {base} of {project}", "fr": "Réparer {base} de {project}"},
    "repair-body": {
        "en": (
            "`{base}` of {project} is red: every open pull request of the repository is "
            "stopped by it. Failing jobs:\n\n{jobs}\n\nFound while checking {url}. Fix "
            "`{base}` so that its CI is green again; the pull requests set aside for it are "
            "replayed on their own once it is."
        ),
        "fr": (
            "`{base}` de {project} est rouge : toutes les pull requests ouvertes du dépôt "
            "en sont bloquées. Jobs en échec :\n\n{jobs}\n\nConstaté en vérifiant {url}. "
            "Répare `{base}` pour que sa CI redevienne verte ; les pull requests mises de "
            "côté pour elle sont rejouées toutes seules dès qu'elle l'est."
        ),
    },
    "checks-failed-on": {
        "en": "CI: red on {names}, where `{base}` is not.",
        "fr": "CI : rouge sur {names}, là où `{base}` ne l'est pas.",
    },
    "checks-unstarted": {
        "en": "CI: did not start — GitHub says: {reason}",
        "fr": "CI : pas démarrée — GitHub dit : {reason}",
    },
    "checks-pending": {
        "en": "CI: still running when the merge was asked.",
        "fr": "CI : encore en cours au moment de la fusion.",
    },
    "checks-none": {"en": "CI: none to wait for.", "fr": "CI : aucune à attendre."},
    "base-moved-again": {
        "en": "Pushed, but the base moved again in the meantime: replayed once more on the next pass.",
        "fr": "Poussée, mais la base a encore bougé entre-temps : rejouée à nouveau au prochain passage.",
    },
    "no-pull-request": {
        "en": "it was validated, but there is no pull request to merge",
        "fr": "il a été validé, mais il n'y a aucune pull request à fusionner",
    },
    "no-pull-request-detail": {
        "en": (
            "Its project — {project} — is a repository, so there is nothing to publish "
            "either. Was the pull request ever opened?"
        ),
        "fr": (
            "Son projet — {project} — est un dépôt, donc il n'y a rien à publier non "
            "plus. La pull request a-t-elle seulement été ouverte ?"
        ),
    },
    "no-pull-request-question": {
        "en": "This ticket was validated but carries no pull request.",
        "fr": "Ce ticket a été validé mais ne porte aucune pull request.",
    },
    "worktree-kept": {
        "en": "The worktree is kept as it was left: `{path}`, on branch `{branch}`.",
        "fr": "Le worktree est conservé tel quel : `{path}`, sur la branche `{branch}`.",
    },
    "workdir-kept": {
        "en": "The working directory is kept as it was left: `{path}`.",
        "fr": "Le répertoire de travail est conservé tel quel : `{path}`.",
    },
    "no-pull-request-opened": {
        "en": "The pull request could not be opened: {error}",
        "fr": "La pull request n'a pas pu être ouverte : {error}",
    },
    "rebased-onto": {
        "en": "The branch was replayed onto `{base}` before the pull request was opened.",
        "fr": "La branche a été rejouée sur `{base}` avant l'ouverture de la pull request.",
    },
    "rebase-refused": {
        "en": (
            "The branch could not be replayed onto `{base}` — {error}. The pull request "
            "is opened as it stands, and shows the conflict."
        ),
        "fr": (
            "La branche n'a pas pu être rejouée sur `{base}` — {error}. La pull request "
            "est ouverte telle quelle et montre le conflit."
        ),
    },
    # -- a run with nothing left to spend -------------------------------------
    "credit-spent-kept": {
        "en": "What the session had already committed is kept on `{branch}`.",
        "fr": "Ce que la session avait déjà commité est conservé sur `{branch}`.",
    },
    "credit-parked": {
        "en": "nothing was started for it, and nothing is wrong with it: "
        "the credit comes back at {when}",
        "fr": "rien n'a été lancé pour lui, et rien ne cloche de son côté : "
        "le crédit revient à {when}",
    },
    # -- a run that died in the middle ---------------------------------------
    "abandoned-requeued": {
        "en": "I am picking it up again from the start.",
        "fr": "Je le reprends depuis le début.",
    },
    # -- a blocked ticket looked at again --------------------------------------
    "unblocked": {"en": "No longer blocked: {reason}", "fr": "Plus bloqué : {reason}"},
    "kept-blocked": {
        "en": "🔒 Still blocked: {reason}",
        "fr": "🔒 Toujours bloqué : {reason}",
    },
    # -- the prompt of the « On » column --------------------------------------
    "on-failed": {
        "en": "⚠️ The « On » prompt failed on {old} → {new}: {reason}",
        "fr": "⚠️ Le prompt « On » a échoué sur {old} → {new} : {reason}",
    },
    "on-over-budget": {
        "en": "it reached its spending limit (${limit:.2f}) before the end",
        "fr": "il a atteint son plafond de dépense ({limit:.2f} $) avant la fin",
    },
    "on-nothing": {"en": "the session said nothing", "fr": "la session n'a rien dit"},
    # -- a branch a ticket already had ----------------------------------------
    # Facts only git has, said here rather than by `git.py`: the worktree it
    # hands back carries them bare, and the run says them in its own words.
    "branch-there": {
        "en": "Branch `{branch}` was already there ({why}, {commits})",
        "fr": "La branche `{branch}` existait déjà ({why}, {commits})",
    },
    "branch-held": {"en": "its worktree was still there", "fr": "son worktree était encore là"},
    "branch-left": {
        "en": "an earlier attempt left it",
        "fr": "une tentative précédente l'a laissée",
    },
    "branch-pushed": {
        "en": "it was pushed but never merged",
        "fr": "elle a été poussée mais jamais fusionnée",
    },
    "branch-own-commits": {"en": "{count} commit(s)", "fr": "{count} commit(s)"},
    "branch-no-commit": {"en": "no commit of its own", "fr": "aucun commit à elle"},
    "branch-rebased": {
        "en": "{was}, rebased onto `{start}` and picked up where it stopped.",
        "fr": "{was}, rejouée sur `{start}` et reprise là où elle s'était arrêtée.",
    },
    "worktree-backup": {
        "en": (
            "An earlier session left its worktree interrupted (a rebase, a merge or a detached "
            "HEAD with changes): what it held is saved on the local branch `{backup}` (`git log -p {base}..{backup}`), "
            "and the ticket starts again from its own branch."
        ),
        "fr": (
            "Une session précédente a laissé son worktree interrompu (rebase, merge ou HEAD "
            "détachée avec des modifications) : ce qu'il contenait est sauvegardé sur la branche locale `{backup}` "
            "(`git log -p {base}..{backup}`), et le ticket repart de sa propre branche."
        ),
    },
    "branch-as-it-stands": {
        "en": (
            "{was} and is reused as it stands: it does not replay onto `{start}` — "
            "{failure}. Whatever it is behind on is for this session to deal with."
        ),
        "fr": (
            "{was} et est reprise telle quelle : elle ne se rejoue pas sur `{start}` — "
            "{failure}. Le retard qu'elle a, c'est à cette session de s'en occuper."
        ),
    },
    # -- what a pull request is opened with -----------------------------------
    "pull-request-body": {
        "en": (
            "{summary}\n\n---\nNotion ticket: {url}\nClaude Code session: `{session}`\n"
            "Opened by ponos ({commits})."
        ),
        "fr": (
            "{summary}\n\n---\nTicket Notion : {url}\nSession Claude Code : `{session}`\n"
            "Ouverte par ponos ({commits})."
        ),
    },
    # -- a ticket born of a schedule ------------------------------------------
    "born-of-schedule": {
        "en": "*Born of the “{name}” schedule, {stamp}* — {url}",
        "fr": "*Né de la récurrence « {name} », {stamp}* — {url}",
    },
    # -- the folded block, when it is longer than it is worth ------------------
    "too-many-steps": {
        "en": "more than {count} paragraphs — the rest is in the log",
        "fr": "plus de {count} paragraphes — la suite est dans le journal",
    },
    # -- talking in a thread --------------------------------------------------
    "no-reply": {
        "en": "I could not answer this one: {error}.\nIts log is `{log}`.",
        "fr": "Je n'ai pas réussi à répondre à celle-ci : {error}.\nSon journal est `{log}`.",
    },
    "said-nothing": {
        "en": "the session ended without saying anything",
        "fr": "la session s'est terminée sans rien dire",
    },
    # -- what reaches a phone -------------------------------------------------
    # The title of a desktop or Telegram notification, where the ticket has to
    # be named — Notion puts the page's own name above the comment, and these
    # two have nothing but what they are handed. The words are the verdicts'.
    "headline": {"en": "{verdict} · {title}", "fr": "{verdict} · {title}"},
    "publication-interrupted": {
        "en": "its publication was interrupted — did it go out? If not, back to “{origin}”",
        "fr": "sa publication a été interrompue — est-elle partie ? Sinon, retour "
        "dans « {origin} »",
    },
    # -- about the runner itself, wherever you are reachable ------------------
    "out-of-credit": {"en": "Ponos is out of credit", "fr": "Ponos n'a plus de crédit"},
    "out-of-credit-detail": {"en": "Back to work at {when}.", "fr": "Retour au travail à {when}."},
    "credit-again": {"en": "Ponos has credit again", "fr": "Ponos a de nouveau du crédit"},
    "credit-again-detail": {
        "en": "{used}% of the subscription spent — back to work.",
        "fr": "{used} % de l'abonnement consommé — retour au travail.",
    },
    "budget-reached": {
        "en": "Ponos reached today's spending limit",
        "fr": "Ponos a atteint le plafond de dépense du jour",
    },
    "budget-reached-detail": {
        "en": "{spent} spent today, limit {limit} — nothing new is started before {when}.",
        "fr": "{spent} dépensés aujourd'hui, plafond {limit} — rien de nouveau ne démarre avant {when}.",
    },
    "budget-parked": {
        "en": "nothing was started for it: today's spending limit is reached, it resumes at {when}",
        "fr": "rien n'a été lancé pour lui : le plafond de dépense du jour est atteint, il reprend à {when}",
    },
    "reserve-reached": {
        "en": "Ponos is leaving you the rest",
        "fr": "Ponos te laisse le reste",
    },
    "reserve-reached-detail": {
        "en": (
            "{used}% of the subscription spent, {reserve}% reserved — nothing new is "
            "started before {when}."
        ),
        "fr": (
            "{used} % de l'abonnement consommé, {reserve} % en réserve — rien de nouveau "
            "ne démarre avant {when}."
        ),
    },
    # The button a desktop draws under a notification that has a ticket to open.
    "open-ticket": {"en": "Open the ticket", "fr": "Ouvrir le ticket"},
    # And the one beside it when the ticket ended on a pull request.
    "see-pull-request": {"en": "See the PR", "fr": "Voir la PR"},
    # A notification on the desktop says what happened, on which project, and
    # what is left to do — in that order, and with no verdict word borrowed from
    # the comment: "Stuck" on a lock screen is not an event.
    "desktop-title-blocked": {"en": "Ponos has a question", "fr": "Ponos a une question"},
    "desktop-title-failed": {"en": "Ticket failed", "fr": "Ticket en erreur"},
    "desktop-title-done": {"en": "Ticket done", "fr": "Ticket terminé"},
    "desktop-title-prepared": {"en": "To validate", "fr": "À valider"},
    "desktop-title-review": {"en": "To review", "fr": "À relire"},
    "desktop-title-project": {"en": "{event} — {project}", "fr": "{event} — {project}"},
    # What to do about it, when the session has said nothing more specific.
    "desktop-next-blocked": {"en": "A question is waiting", "fr": "Une question attend ta réponse"},
    "desktop-next-failed": {
        "en": "The run stopped on an error",
        "fr": "Le travail s'est arrêté sur une erreur",
    },
    "desktop-next-review": {"en": "A pull request is ready", "fr": "Une pull request est prête"},
    "desktop-next-read": {"en": "The result is ready to read", "fr": "Le résultat est prêt à lire"},
    "desktop-next-merged": {
        "en": "The pull request is merged",
        "fr": "La pull request est fusionnée",
    },
    "desktop-next-published": {"en": "The result is published", "fr": "Le résultat est publié"},
    "desktop-next-prepared": {"en": "Validate it in the ticket", "fr": "Valide-le dans le ticket"},
    "answer-in-ticket": {"en": "Answer in the ticket", "fr": "Réponds dans le ticket"},
    # -- answering from Telegram or Slack -------------------------------------
    # A relayed answer opens on where it came from, and that opening is what
    # tells the next run it is yours — see `openings`, which reads every
    # language's, since a board keeps the answers given before a change of mind.
    "relayed": {"en": "Answered from {channel}", "fr": "Répondu depuis {channel}"},
    "relayed-by": {"en": " by {who}", "fr": " par {who}"},
    "relayed-console": {"en": "the console", "fr": "la console"},
    "relayed-yes": {
        "en": "Yes — go ahead with what you proposed.",
        "fr": "Oui — vas-y avec ce que tu as proposé.",
    },
    "relayed-no": {"en": "No — do not do that.", "fr": "Non — ne fais pas ça."},
    "relayed-option": {"en": "Option {number}: {option}.", "fr": "Option {number} : {option}."},
    # A choice made from the console's Unblock and Decide tabs, said on the
    # ticket under the line that says where it came from — see decisions.py.
    "decision": {"en": "Decision: {choice}.", "fr": "Décision : {choice}."},
    "decided-answer": {"en": "answer to the question", "fr": "réponse à la question"},
    "decided-yes": {"en": "yes, go ahead", "fr": "oui, vas-y"},
    "decided-close": {
        "en": "yes, close it — moved to done",
        "fr": "oui, clos-le — passé en terminé",
    },
    "decided-option": {"en": "option {number}, “{option}”", "fr": "option {number}, « {option} »"},
    "decided-done-retry": {"en": "done by hand, run it again", "fr": "c'est fait, relancer"},
    "decided-retry": {"en": "run it again", "fr": "relancer"},
    "decided-model": {"en": "run it again on {model}", "fr": "relancer avec {model}"},
    "decided-instruct": {
        "en": "run it again with an instruction",
        "fr": "relancer avec une consigne",
    },
    "decided-split": {
        "en": "split into {count} tickets: {titles}",
        "fr": "découpé en {count} tickets : {titles}",
    },
    "offer-split": {"en": "split into sub-tickets", "fr": "découper en sous-tickets"},
    "decided-abandon": {"en": "abandoned, moved to done", "fr": "abandonné, passé en terminé"},
    "decided-abandon-cancelled": {
        "en": "abandoned, moved to cancelled",
        "fr": "abandonné, classé sans suite",
    },
    "decided-other": {"en": "an instruction", "fr": "une consigne"},
    "decided-validate": {"en": "validated", "fr": "validé"},
    "decided-rework": {
        "en": "back to work with an instruction",
        "fr": "renvoyé au travail avec une consigne",
    },
    "decided-fix-ci": {"en": "back to work: fix the checks", "fr": "renvoyé : corriger la CI"},
    "decided-add-tests": {
        "en": "back to work: add the missing tests",
        "fr": "renvoyé : ajouter les tests manquants",
    },
    "decided-screenshots": {
        "en": "back to work: take the screenshots",
        "fr": "renvoyé : faire les captures demandées",
    },
    "decided-rebase": {
        "en": "back to work: rebase onto the base branch",
        "fr": "renvoyé : rebaser sur la branche de base",
    },
    "decided-caveat": {
        "en": "back to work on a point to check",
        "fr": "renvoyé sur un point à vérifier",
    },
    "decided-reject": {"en": "rejected, moved to done", "fr": "rejeté, passé en terminé"},
    "decided-reject-cancelled": {
        "en": "rejected, moved to cancelled",
        "fr": "rejeté, classé sans suite",
    },
    # What the next session is told when the choice carries no words of its own,
    # and what the console offers to send, ready to be edited.
    "told-done-retry": {
        "en": "I did what you asked by hand: check it and carry on.",
        "fr": "J'ai fait à la main ce que tu demandais : vérifie et reprends.",
    },
    "told-close": {
        "en": "Closed as you proposed: nothing more to do on this ticket.",
        "fr": "Clos comme tu le proposais : plus rien à faire sur ce ticket.",
    },
    "told-retry": {
        "en": "Try again, from where you stopped.",
        "fr": "Réessaie, là où tu t'es arrêté.",
    },
    "told-fix-ci": {
        "en": "The checks fail on the pull request: read them and fix what fails.",
        "fr": "Les vérifications échouent sur la pull request : lis-les et corrige ce qui échoue.",
    },
    "told-add-tests": {
        "en": "Add the tests that are missing for what you changed.",
        "fr": "Ajoute les tests qui manquent pour ce que tu as changé.",
    },
    "told-screenshots": {
        "en": "Take the screenshots that were asked for, in the dark and light themes, on desktop and on mobile.",
        "fr": "Fais les captures demandées, en thème sombre et clair, sur desktop et sur mobile.",
    },
    "told-rebase": {
        "en": "Rebase the branch onto the base branch and resolve what conflicts.",
        "fr": "Rebase la branche sur la branche de base et résous les conflits.",
    },
    "told-caveat": {
        "en": "Deal with this before review: {caveat}",
        "fr": "Règle ceci avant la relecture : {caveat}",
    },
    "told-split": {
        "en": "Split from “{title}”: {url}",
        "fr": "Découpé depuis « {title} » : {url}",
    },
    "noted": {
        "en": "✓ noted on “{title}” — it runs again in a moment.",
        "fr": "✓ noté sur « {title} » — il repart dans un instant.",
    },
    "nothing-waiting": {
        "en": (
            "Nothing here is waiting on an answer — reply under the question itself, "
            "or name the ticket."
        ),
        "fr": (
            "Rien n'attend de réponse ici — répondre sous la question elle-même, "
            "ou nommer le ticket."
        ),
    },
    "notion-refused": {
        "en": "Notion refused that answer: {error}",
        "fr": "Notion a refusé cette réponse : {error}",
    },
    # -- an idea kept, as the draft it becomes ---------------------------------
    # The four headings a ticket is written under, so that a kept idea reads
    # like a ticket somebody wrote rather than like a note — see ideas.py.
    "idea-what": {"en": "What", "fr": "Quoi"},
    "idea-where": {"en": "Where", "fr": "Où"},
    "idea-done": {"en": "Done when", "fr": "Fini quand"},
    "idea-out": {"en": "Out of scope", "fr": "Hors périmètre"},
    "idea-frame": {"en": "Frame the project {name}", "fr": "Cadrer le projet {name}"},
    "idea-frame-what": {
        "en": "Turn this idea into a project: who it is for, what the first version does, "
        "what it is built with, and the tickets that get it there.",
        "fr": "Faire de cette idée un projet : pour qui, ce que fait la première version, "
        "avec quoi on la construit, et les tickets qui y mènent.",
    },
    "idea-frame-where": {
        "en": "The project's page, whose brief this ticket writes.",
        "fr": "La page du projet, dont ce ticket écrit le brief.",
    },
    "idea-frame-done": {
        "en": "The brief is written on the project's page, and the first tickets are drafted.",
        "fr": "Le brief est écrit sur la page du projet, et les premiers tickets sont en brouillon.",
    },
    "idea-frame-out": {
        "en": "Building any of it: that is what the tickets are for.",
        "fr": "En construire quoi que ce soit : c'est le rôle des tickets.",
    },
    # -- counted things -------------------------------------------------------
    # Both languages happen to make their plural the same way here, which is
    # luck and not a rule: the day one of them does not, this is where it says so.
    "commit": {"en": "{count} commit", "fr": "{count} commit"},
    "commits": {"en": "{count} commits", "fr": "{count} commits"},
    "block": {"en": "{count} block", "fr": "{count} bloc"},
    "blocks": {"en": "{count} blocks", "fr": "{count} blocs"},
    "step": {"en": "{count} step", "fr": "{count} étape"},
    "steps": {"en": "{count} steps", "fr": "{count} étapes"},
    "minute": {"en": "{count} minute", "fr": "{count} minute"},
    "minutes": {"en": "{count} minutes", "fr": "{count} minutes"},
    "under-a-minute": {"en": "under a minute", "fr": "moins d'une minute"},
    # -- the folded block a run leaves on the page ----------------------------
    # Its title, while the session runs and once it is over. A failed run calls
    # it a trace, because that is what somebody opens it for.
    "live": {"en": "Live", "fr": "En cours"},
    "live-trace": {"en": "Trace", "fr": "Trace"},
    "live-interrupted": {"en": "interrupted", "fr": "interrompu"},
    "live-stopped": {"en": "stopped", "fr": "arrêté"},
    "live-blocked": {"en": "it asked a question", "fr": "il a posé une question"},
    "live-waiting": {
        "en": "out of credit — it will be picked up again",
        "fr": "crédits épuisés — il sera repris",
    },
    # -- what the session is told to write in ---------------------------------
    # Not a report: the sentence handed to `prompt.build`, which is why it is
    # written *to* the session and not about it — and why both rows are in
    # English. A prompt is written in one language whatever it asks for, and a
    # brief that switched languages halfway would be one more thing for the
    # session to interpret.
    "instruction": {
        "en": (
            "Write in English — your report, any question you ask, the final line below, "
            "and anything you write back into the ticket — even when the ticket is written "
            "in another language; only the words `RESULT:`, `ok` and `blocked` stay as "
            "they are. Code, commit messages and identifiers keep the language the "
            "repository already uses."
        ),
        "fr": (
            "Write in French — your report, any question you ask, the final line below, "
            "and anything you write back into the ticket — even when the ticket is written "
            "in another language; only the words `RESULT:`, `ok` and `blocked` stay as "
            "they are. Code, commit messages and identifiers keep the language the "
            "repository already uses."
        ),
    },
    "instruction-reply": {
        "en": "Answer in English, whatever language the message you are answering is in.",
        "fr": "Answer in French, whatever language the message you are answering is in.",
    },
}


def every(key: str) -> tuple[str, ...]:
    """A sentence as each language says it, for what is read back as well as written."""
    return tuple(dict.fromkeys(_SAID[key].values()))


def openings(key: str) -> tuple[str, ...]:
    """How a phrase begins, in every language — what comes before its first blank.

    For the sentences that are *recognised* as well as written: the board keeps
    what was said in English the day before `runner.language` turned to French,
    and those still have to be read as what they were.
    """
    return tuple(dict.fromkeys(text.split("{", 1)[0] for text in _SAID[key].values()))


class Voice:
    """The runner's own words, in the language the configuration asked for.

    Built from what the file literally says rather than from the language that
    was read out of it, because those are two different questions: `fr` and `en`
    both name a language, while *nothing at all* also says the sessions were
    never told what to write in — see `instruction`.
    """

    def __init__(self, language: str = "") -> None:
        self.asked = str(language or "").strip()
        self.language = understood(self.asked)

    # -- the sentence itself -------------------------------------------------

    def say(self, key: str, **values: object) -> str:
        """One thing the runner has to say, filled in."""
        return _SAID[key][self.language].format(**values)

    def count(self, number: int, thing: str) -> str:
        """“3 commits”, “1 commit” — the noun's key is its singular."""
        return self.say(thing if abs(number) == 1 else f"{thing}s", count=number)

    def minutes(self, seconds: float) -> str:
        """How long something took, said the way a person would.

        “18.2 min” is a measurement; nobody reports their afternoon to the tenth
        of a minute. Under a minute it stops being a number at all.
        """
        if seconds < 60:
            return self.say("under-a-minute")
        return self.count(round(seconds / 60), "minute")

    def money(self, dollars: float) -> str:
        """A price, with the currency where each language puts it."""
        if self.language == "fr":
            return f"{dollars:.2f} $".replace(".", ",")
        return f"${dollars:.2f}"

    # -- a report under a ticket ---------------------------------------------

    def facts(self, *facts: object) -> str:
        """The figures that place a verdict, in the order somebody reads them.

        Where the work is, how much of it there is, what it took — separated by
        a middle dot, because a comma would read as a sentence and this is a
        row of labels.
        """
        return " · ".join(said for fact in facts if (said := str(fact or "").strip()))

    def verdict(self, name: str, *facts: object) -> str:
        """The first line of a report, which is the notification.

        A mark, one word saying what is expected of you, and the figures. It has
        about eighty characters before a phone stops showing it, so nothing else
        goes here — and nothing at all goes in front of it, which is the whole
        difference with the reports that opened on the name of a machine.
        """
        said = f"{MARKS[name]} {self.say('verdict-' + name)}"
        placed = self.facts(*facts)
        return f"{said} — {placed}" if placed else said

    def headline(self, name: str, title: str) -> str:
        """A notification's title: the same verdict, and what it is about.

        Notion writes the page's name above the comment it pushes; a desktop
        notification and a Telegram message have only what they are handed, so
        the ticket is named here — and named with the verdict the comment opens
        on, so that the two read as one thing said twice.
        """
        return self.say("headline", verdict=self.say("verdict-" + name), title=title)

    def desktop(
        self,
        name: str,
        title: str,
        *,
        project: str = "",
        summary: object = "",
    ) -> tuple[str, str]:
        """A desktop notification's title and body, which are not the comment's.

        The comment is read in Notion, where a link is a link and Markdown is
        drawn; a desktop shows a few lines of plain text, and a click on any of
        it opens the ticket. So nothing goes here that only makes sense in a
        comment — no address, no price, no duration, no backticks — and what is
        said is, in order: the event and its project (the title, which is all a
        lock screen keeps), then the ticket's name, cut on a word, and one
        sentence — the session's own, or what is expected of you. A question is
        said as a question, without the options: nobody answers one from there.
        """
        project, title = _project_and_title(title, project)
        kind = _DESKTOP_EVENT.get(name)
        event = self.say("desktop-title-" + kind if kind else "verdict-" + name)
        heading = (
            self.say("desktop-title-project", event=event, project=project) if project else event
        )
        sentence = self.brief(_bare(summary), GIST) or self.say(
            "desktop-next-" + name if name in _DESKTOP_NEXT else "desktop-next-failed"
        )
        lines = [self.brief(_bare(title), TITLE), sentence]
        if name == "blocked":
            lines.append(self.say("answer-in-ticket"))
        return heading, "\n".join(_escaped(line) for line in lines if line)

    def report(self, headline: str, *lines: object) -> str:
        """One comment: the verdict, one sentence, one link. In that order.

        Three lines, and the order is the point — a reader who stops after the
        first has the decision, one who stops after the second has the story,
        and the third is where they go. A run that went wrong is allowed one
        more, saying where the rest of it is, because that is the day somebody
        needs it.
        """
        return "\n".join(said for line in (headline, *lines) if (said := str(line or "").strip()))

    def brief(self, text: object, limit: int = BRIEF) -> str:
        """What the session said, cut on a word rather than mid-syllable.

        The prompt asks for one sentence and mostly gets one; asking is not
        enforcing, and a report is not the place to find out. Cut here, once,
        rather than by whatever is showing it.
        """
        flat = " ".join(str(text or "").split())
        if len(flat) <= limit:
            return flat
        return flat[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"

    def question(self, asked: object) -> list[str]:
        """A blocked ticket's question, one line per idea, under its verdict.

        Why it stops, then the question laid out for the answer it wants: a
        yes-no question carries the two words that answer it, a choice its
        options numbered on one line — so that “2” is an answer and the comment
        still fits on a phone — and a free question stands alone. What is done
        is not here: it goes on the verdict line, which is the notification.
        See question.py for the three kinds.
        """
        ask = self.brief(getattr(asked, "ask", ""))
        mode = getattr(asked, "mode", "free")
        if mode == "yes-no":
            ask = f"{ask} → {self.say('yes-or-no')}"
        why = self.brief(getattr(asked, "why", ""))
        # The kind of thing it stopped on, when the session named it: in front
        # of why, which is where the console reads it back — decisions.py.
        category = getattr(asked, "category", "")
        if category:
            named = self.say(f"category-{category}")
            why = self.say("because", category=named, why=why) if why else named
        lines = [why]
        if getattr(asked, "code", ""):
            lines.append(f"`{asked.code}`")
        # The commands a session could not run itself, ready to paste, between
        # the reason and the question — which stays the last line, as `found`
        # reads it back.
        lines += [f"`{command}`" for command in getattr(asked, "commands", [])]
        lines.append(ask)
        if mode == "choice":
            options = getattr(asked, "options", [])
            lines.append(
                " · ".join(
                    f"{index}. {self.brief(option, 60)}" for index, option in enumerate(options, 1)
                )
            )
        return [line for line in lines if line]

    def caveats(self, caveats: object) -> list[str]:
        """What a session could not check, one line each, as a review report says it."""
        return [
            self.say("caveat", text=self.brief(caveat))
            for caveat in caveats or ()
            if str(caveat).strip()
        ]

    def paragraphs(self, *parts: object) -> str:
        """Whatever is worth saying, one paragraph each, blanks dropped.

        Most of what goes under a report is optional — a note, a kept worktree,
        a price — and a message assembled with f-strings around things that may
        be empty ends up with the blank lines to prove it.
        """
        return "\n\n".join(said for part in parts if (said := str(part or "").strip()))

    def sentence(self, text: str) -> str:
        """A reason, read as a sentence rather than as a label.

        The reasons are written lowercase and unpunctuated because that is how
        they read in the journal — “✗ Le header — the session did not make it to
        the end”. On a ticket they are the first thing said, and the first thing
        said is a sentence.
        """
        text = text.strip()
        if not text:
            return ""
        return text[:1].upper() + text[1:] + ("" if text[-1] in ".!?…" else ".")

    def spent(self, seconds: float, cost: float) -> tuple[str, ...]:
        """What the run took, as facts for a verdict line rather than a sentence.

        Two of them, not three: the turn count is on the board already, in its
        own column, and a notification has room for what changes a decision.
        """
        return (self.minutes(seconds), self.money(cost) if cost else "")

    def pull_request(self, url: str) -> str:
        """“PR #19”, which is how anybody refers to one out loud.

        The URL says the same thing in seventy characters, and a verdict line has
        about eighty in all — so the number goes on that line and the URL goes on
        its own, where it is a link to click rather than a fact to read.
        """
        found = re.search(r"/pull/(\d+)", str(url or ""))
        return self.say("pull-request", number=found.group(1)) if found else ""

    def trace(self, resume: str, log: object, home: object = "") -> str:
        """Where to go when the report is not enough: the session, then the log."""
        picker = self.say("trace-picker", home=home) if home else ""
        return self.say("trace", resume=resume, picker=picker, log=log)

    def branch_note(self, worktree: object) -> str:
        """What a ticket's comment says about a branch it already had, or nothing.

        Read off a `git.Worktree` — its facts, not a sentence: see its docstring.
        A branch drawn fresh says nothing, which is the ordinary case.
        """
        if not getattr(worktree, "reused", False):
            return ""
        carried = int(getattr(worktree, "carried", 0) or 0)
        was = self.say(
            "branch-there",
            branch=getattr(worktree, "branch", ""),
            why=self.say(f"branch-{getattr(worktree, 'why', '') or 'left'}"),
            commits=(
                self.say("branch-own-commits", count=carried)
                if carried
                else self.say("branch-no-commit")
            ),
        )
        start = getattr(worktree, "start", "")
        if failure := getattr(worktree, "failure", ""):
            return self.say("branch-as-it-stands", was=was, start=start, failure=failure)
        return self.say("branch-rebased", was=was, start=start)

    def backup_note(self, worktree: object, base: str) -> str:
        """What a ticket's comment says about an interrupted worktree, or nothing."""
        backup = getattr(worktree, "backup", "")
        return self.say("worktree-backup", backup=backup, base=base) if backup else ""

    def pull_request_body(self, summary: str, url: str, session: str, commits: int) -> str:
        """What a pull request the runner opens says under the session's summary."""
        return self.say(
            "pull-request-body",
            summary=summary,
            url=url,
            session=session,
            commits=self.count(commits, "commit"),
        )

    # -- what the session is told --------------------------------------------

    def instruction(self, *, reply: bool = False) -> str:
        """The language a session is told to write in, or nothing at all.

        Nothing when the configuration says nothing, and that is the whole of
        the default: a runner nobody has configured behaves exactly as it did,
        which for a session means the rule its prompt already carries — write in
        the language of the ticket, of the message, of whoever is being answered.

        `reply` is the same sentence for a session that is talking rather than
        working: it has no report to write and no ticket to write back into, and
        the one thing it has to be told is the one thing that is otherwise
        decided by the message it answers.
        """
        if not self.asked:
            return ""
        return self.say("instruction-reply" if reply else "instruction")
