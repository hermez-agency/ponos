"""Why a ticket stopped, as a code rather than as a sentence.

Every blocked or failed ticket used to keep only the sentence it was told in:
the same cause written three ways over a month — the wording changed, the
language changed — and a question as plain as "how many tickets stopped on a
red CI this week" answered by reading 350 sentences and sorting them by hand.
So a stop has a **code**, `domain.cause`, given where the stop is decided
(`_fail(code=…)`) and kept everywhere it goes: the history line, the run, the
board's « Blocage » column, the card in the console. The sentence is still
said, from the voice key the cause names; it is the code that is counted.

Each cause also says what a person needs at a glance and the runner needs to
act on it later, in one place rather than in every caller:

- its **family** — merge, session, infrastructure, question, access — which is
  the icon on the card and the colour of the chart;
- **who** has to move: Ponos itself, you, or something outside both (GitHub,
  Notion);
- a short **label** and one line of **help**, in the two languages the runner
  speaks — not in `voice.py`, because they are not said on a ticket but drawn
  on a card, beside the board's own words;
- the **action** the card offers: run it again, answer, clean, look at the CI
  or at the pull request;
- a **policy**, which is what the runner may do on its own: try again `n`
  times (`retry:n`), wait for the base to be green (`wait-base`), or ask
  (`ask`). Written down here so that the next tickets read it rather than
  decide it again.

A code is never renamed once it has been written: the board's select options
and the history are spelled with it. A new cause is a new code.

**The sentences of the past are read back too** (`classify`): the history kept
before codes existed is reclassed from its sentence, French or English, by the
fragments in `_HEARD` — a migration of `ponos.db` runs it once. What matches
nothing is `unknown`, rather than a guess.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# The families, in the order a legend lists them.
FAMILIES = ("merge", "session", "infrastructure", "question", "access")

# Who has to move for the ticket to move again.
WHO = ("ponos", "user", "external")

# What the card offers, beside the cause.
ACTIONS = ("retry", "answer", "clean", "base-ci", "open-pr")

UNKNOWN = "unknown"


@dataclass(frozen=True)
class Cause:
    code: str
    family: str
    who: str
    action: str
    policy: str
    label: dict[str, str]
    help: dict[str, str]
    # The voice keys its sentence is said with: the first is the one a caller
    # with nothing more specific to say uses.
    said: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """What the console is handed: everything but the voice keys."""
        return {
            "code": self.code,
            "family": self.family,
            "who": self.who,
            "action": self.action,
            "policy": self.policy,
            "label": dict(self.label),
            "help": dict(self.help),
        }


def _cause(
    code: str,
    family: str,
    who: str,
    action: str,
    policy: str,
    label: tuple[str, str],
    help: tuple[str, str],
    *said: str,
) -> Cause:
    return Cause(
        code,
        family,
        who,
        action,
        policy,
        {"en": label[0], "fr": label[1]},
        {"en": help[0], "fr": help[1]},
        said,
    )


_CAUSES = (
    # -- the merge chain ------------------------------------------------------
    _cause(
        "merge.base-red",
        "merge",
        "external",
        "base-ci",
        "wait-base",
        ("Base is red", "Base rouge"),
        (
            "The base branch's own CI fails: nothing merges onto it until it is green again.",
            "La CI de la branche de base échoue : rien n'y fusionne tant qu'elle n'est pas verte.",
        ),
    ),
    _cause(
        "merge.checks-failed",
        "merge",
        "ponos",
        "open-pr",
        "retry:1",
        ("Checks failed", "Vérifications rouges"),
        (
            "The pull request's checks fail once its conflicts were resolved: look at what broke.",
            "Les vérifications de la pull request échouent après la résolution des conflits : regardez ce qui a cassé.",
        ),
        "checks-red",
    ),
    _cause(
        "merge.local-ci-failed",
        "merge",
        "user",
        "answer",
        "ask",
        ("Local CI red", "CI locale rouge"),
        (
            "The project's CI, run on this machine before the pull request, still fails after "
            "every attempt: say what to fix, or turn the local CI off for the project.",
            "La CI du projet, lancée sur cette machine avant la pull request, échoue encore "
            "après toutes les tentatives : dites quoi corriger, ou désactivez la CI locale du "
            "projet.",
        ),
    ),
    _cause(
        "merge.base-moving",
        "merge",
        "ponos",
        "retry",
        "wait-base",
        ("Base moving too fast", "Base trop mouvante"),
        (
            "The base moved between every replay: merge it by hand, or run it again when it is quieter.",
            "La base a bougé entre chaque rejeu : fusionnez à la main, ou relancez quand elle est plus calme.",
        ),
        "rebased-too-often",
    ),
    _cause(
        "merge.refused",
        "merge",
        "external",
        "open-pr",
        "ask",
        ("Merge refused", "Fusion refusée"),
        (
            "GitHub would not merge the pull request: its page says why.",
            "GitHub n'a pas voulu fusionner la pull request : sa page dit pourquoi.",
        ),
        "merge-refused",
    ),
    _cause(
        "merge.conflict-decision",
        "merge",
        "user",
        "answer",
        "ask",
        ("Conflict to decide", "Conflit à trancher"),
        (
            "The conflict with the base needs a choice only you can make: answer on the ticket.",
            "Le conflit avec la base demande un choix que vous seul pouvez faire : répondez sur le ticket.",
        ),
        "conflict-open",
    ),
    _cause(
        "merge.conflict-unfinished",
        "merge",
        "ponos",
        "retry",
        "retry:1",
        ("Conflicts left open", "Conflits inachevés"),
        (
            "The session said it resolved the conflicts and did not: nothing was pushed.",
            "La session dit avoir résolu les conflits et ne l'a pas fait : rien n'a été poussé.",
        ),
        "conflict-unfinished",
    ),
    _cause(
        "merge.pushed-over",
        "merge",
        "user",
        "answer",
        "ask",
        ("Branch pushed meanwhile", "Branche poussée entre-temps"),
        (
            "Someone else pushed to the branch while it was being resolved: say which side wins.",
            "Quelqu'un a poussé sur la branche pendant la résolution : dites quel côté l'emporte.",
        ),
        "pushed-over",
    ),
    _cause(
        "merge.push-refused",
        "merge",
        "external",
        "retry",
        "retry:2",
        ("Push refused", "Push refusé"),
        (
            "The commits are kept on this machine, but the remote refused them.",
            "Les commits sont gardés sur cette machine, mais le dépôt distant les a refusés.",
        ),
        "push-refused",
    ),
    _cause(
        "merge.no-pr",
        "merge",
        "user",
        "answer",
        "ask",
        ("No pull request", "Pas de pull request"),
        (
            "It was validated, but there is no pull request to merge: was one ever opened?",
            "Il a été validé, mais il n'y a aucune pull request à fusionner : en a-t-on ouvert une ?",
        ),
        "no-pull-request",
    ),
    _cause(
        "merge.pr-closed",
        "merge",
        "user",
        "open-pr",
        "ask",
        ("Pull request closed", "Pull request fermée"),
        (
            "Its pull request was closed rather than merged: reopen it, or run the ticket again.",
            "Sa pull request a été fermée au lieu d'être fusionnée : rouvrez-la, ou relancez le ticket.",
        ),
        "pull-request-closed",
    ),
    # -- a session that came back with nothing --------------------------------
    _cause(
        "session.killed",
        "session",
        "ponos",
        "retry",
        "retry:1",
        ("Session cut short", "Session interrompue"),
        (
            "The session did not make it to the end: its log says where it stopped.",
            "La session n'est pas allée au bout : son journal dit où elle s'est arrêtée.",
        ),
        "session-failed",
    ),
    _cause(
        "session.not-started",
        "infrastructure",
        "ponos",
        "retry",
        "retry:2",
        ("Session not started", "Session pas démarrée"),
        (
            "The Claude session would not start: check that the CLI runs on this machine.",
            "La session Claude n'a pas voulu démarrer : vérifiez que le CLI tourne sur cette machine.",
        ),
        "no-session",
    ),
    _cause(
        "session.no-answer",
        "session",
        "ponos",
        "retry",
        "retry:1",
        ("No answer written", "Aucune réponse écrite"),
        (
            "The session stopped without writing its answer.",
            "La session s'est arrêtée sans écrire sa réponse.",
        ),
        "no-answer",
    ),
    _cause(
        "session.no-commit",
        "session",
        "ponos",
        "retry",
        "retry:1",
        ("Nothing committed", "Aucun commit"),
        (
            "The session called itself done without a single commit.",
            "La session s'est déclarée terminée sans un seul commit.",
        ),
        "nothing-committed",
    ),
    _cause(
        "session.question",
        "question",
        "user",
        "answer",
        "ask",
        ("Question for you", "Question pour vous"),
        (
            "The session stopped to ask you something: answer on the ticket and it carries on.",
            "La session s'est arrêtée pour vous poser une question : répondez sur le ticket et elle reprend.",
        ),
        "asked-something",
    ),
    _cause(
        "session.over-budget",
        "session",
        "user",
        "answer",
        "ask",
        ("Spending limit reached", "Plafond de dépense atteint"),
        (
            "The session reached the ticket's spending limit: raise it or split the ticket, then answer.",
            "La session a atteint le plafond du ticket : relevez-le ou découpez le ticket, puis répondez.",
        ),
        "over-ticket-budget",
    ),
    _cause(
        "publish.failed",
        "session",
        "ponos",
        "retry",
        "retry:1",
        ("Publication failed", "Publication échouée"),
        (
            "It was validated, but publishing it did not work: the working folder is kept.",
            "Il a été validé, mais la publication n'a pas fonctionné : le dossier de travail est gardé.",
        ),
        "not-published",
    ),
    # -- Ponos's own machinery ------------------------------------------------
    _cause(
        "worktree.residue",
        "infrastructure",
        "ponos",
        "clean",
        "retry:1",
        ("Worktree in the way", "Worktree encombré"),
        (
            "The ticket's worktree could not be made, usually because of a folder left behind: ponos clean, then run it again.",
            "Le worktree du ticket n'a pas pu être créé, souvent à cause d'un dossier resté là : ponos clean, puis relancez.",
        ),
        "no-worktree",
    ),
    _cause(
        "worktree.interrupted",
        "infrastructure",
        "user",
        "answer",
        "ask",
        ("Work interrupted", "Travail interrompu"),
        (
            "A run on it stopped half-way: say whether to start it over.",
            "Un passage s'est arrêté à mi-chemin : dites s'il faut le reprendre.",
        ),
        "publication-interrupted",
    ),
    _cause(
        "runner.crashed",
        "infrastructure",
        "ponos",
        "retry",
        "retry:1",
        ("Ponos crashed", "Ponos a planté"),
        (
            "The runner itself broke on this ticket: the error is in its comment.",
            "Le runner lui-même a cassé sur ce ticket : l'erreur est dans son commentaire.",
        ),
        "crashed",
    ),
    _cause(
        "notion.write-failed",
        "infrastructure",
        "external",
        "retry",
        "retry:2",
        ("Notion refused the write", "Écriture Notion refusée"),
        (
            "The answer could not be written to the ticket; it is still on disk.",
            "La réponse n'a pas pu être écrite dans le ticket ; elle est toujours sur le disque.",
        ),
        "answer-not-written",
    ),
    _cause(
        "notion.read-failed",
        "infrastructure",
        "external",
        "retry",
        "retry:2",
        ("Ticket unreadable", "Ticket illisible"),
        (
            "What the ticket says could not be read from the board.",
            "Ce que dit le ticket n'a pas pu être lu sur le board.",
        ),
        "unreadable",
    ),
    # -- what only a person can give ------------------------------------------
    _cause(
        "access.sudo",
        "access",
        "user",
        "answer",
        "ask",
        ("Needs sudo", "Demande sudo"),
        (
            "The work needs a command run as root, which a session is not allowed to.",
            "Le travail demande une commande en root, ce qu'une session n'a pas le droit de faire.",
        ),
    ),
    _cause(
        "access.credentials",
        "access",
        "user",
        "answer",
        "ask",
        ("Credentials missing", "Identifiants manquants"),
        (
            "The work needs an access or a key this machine does not have.",
            "Le travail demande un accès ou une clé que cette machine n'a pas.",
        ),
    ),
    _cause(
        "project.no-repo",
        "access",
        "user",
        "retry",
        "ask",
        ("Project not found", "Projet introuvable"),
        (
            "Its project's repository is not on this machine: fix the project's page, then run it again.",
            "Le dépôt de son projet n'est pas sur cette machine : corrigez la page du projet, puis relancez.",
        ),
        "no-project",
    ),
    _cause(
        "ticket.empty",
        "question",
        "user",
        "answer",
        "ask",
        ("Empty ticket", "Ticket vide"),
        (
            "There is nothing to work from: give it a title or a description.",
            "Il n'y a rien pour commencer : donnez-lui un titre ou une description.",
        ),
        "empty-ticket",
    ),
    _cause(
        "ticket.kind-unsure",
        "question",
        "user",
        "answer",
        "ask",
        ("Type to choose", "Type à choisir"),
        (
            "Ponos could not tell which kind of ticket this is: choose it in the Type column.",
            "Ponos n'a pas su dire de quel type est ce ticket : choisissez-le dans la colonne Type.",
        ),
        "kind-unknown",
        "kind-unsure",
        "kind-hesitant",
    ),
    _cause(
        UNKNOWN,
        "infrastructure",
        "ponos",
        "retry",
        "ask",
        ("Unclassified", "Non classé"),
        (
            "A stop from before causes had codes, whose sentence matched none of them.",
            "Un arrêt d'avant les codes, dont la phrase ne correspond à aucun d'eux.",
        ),
    ),
)

CAUSES: dict[str, Cause] = {cause.code: cause for cause in _CAUSES}

# The codes, in catalogue order — what the board's select offers.
CODES: tuple[str, ...] = tuple(CAUSES)


def cause(code: str) -> Cause:
    """The cause of a code, or `ValueError` for one the catalogue does not hold."""
    try:
        return CAUSES[code]
    except KeyError:
        raise ValueError(f"no such block code: {code!r} — see blocks.py") from None


def known(code: object) -> str:
    """A code read off the board or a file, as one of ours — `""` for anything else."""
    text = str(code or "").strip()
    return text if text in CAUSES else ""


def describe(code: str) -> dict[str, object] | None:
    """What the console draws for a code, or None for a code it should not draw."""
    found = CAUSES.get(code)
    return found.as_dict() if found else None


# -- the sentences of the past ---------------------------------------------

# A fragment of a sentence the runner once wrote, and the cause it was said
# for: today's sentences and the older ones the history still holds, in both
# languages. Read in order, and the first fragment found wins — the specific
# ones come before "worktree", which a sentence about anything may mention.
# Frozen: the migration that reclasses the history reads it, and a migration
# does not change once it has run.
_HEARD: tuple[tuple[str, str], ...] = (
    ("checks fail", "merge.checks-failed"),
    ("verifications echouent", "merge.checks-failed"),
    ("keeps moving faster", "merge.base-moving"),
    ("avance plus vite", "merge.base-moving"),
    ("would not merge", "merge.refused"),
    ("could not be merged", "merge.refused"),
    ("n'a pas voulu fusionner", "merge.refused"),
    ("conflict needs a decision", "merge.conflict-decision"),
    ("demande une decision", "merge.conflict-decision"),
    ("not fully resolved", "merge.conflict-unfinished"),
    ("pas ete entierement resolus", "merge.conflict-unfinished"),
    ("since the runner last did", "merge.pushed-over"),
    ("depuis le dernier passage du runner", "merge.pushed-over"),
    ("closed rather than merged", "merge.pr-closed"),
    ("fermee au lieu d'etre fusionnee", "merge.pr-closed"),
    ("no pull request", "merge.no-pr"),
    ("aucune pull request", "merge.no-pr"),
    ("push was refused", "merge.push-refused"),
    ("pushing them was refused", "merge.push-refused"),
    ("push a ete refuse", "merge.push-refused"),
    ("worktree", "worktree.residue"),
    ("publishing it did not work", "publish.failed"),
    ("publication n'a pas fonctionne", "publish.failed"),
    ("spending limit", "session.over-budget"),
    ("plafond de depense", "session.over-budget"),
    ("to ask you", "session.question"),
    ("poser une question", "session.question"),
    ("without deciding", "session.question"),
    ("without writing an answer", "session.no-answer"),
    ("sans ecrire de reponse", "session.no-answer"),
    ("without answering", "session.no-answer"),
    ("without committing", "session.no-commit"),
    ("without a single commit", "session.no-commit"),
    ("sans un seul commit", "session.no-commit"),
    ("make it to the end", "session.killed"),
    ("pas allee au bout", "session.killed"),
    ("session failed", "session.killed"),
    ("would not start", "session.not-started"),
    ("could not be started", "session.not-started"),
    ("n'a pas voulu demarrer", "session.not-started"),
    ("answer could not be written", "notion.write-failed"),
    ("write the answer", "notion.write-failed"),
    ("ecrire la reponse", "notion.write-failed"),
    ("runner itself broke", "runner.crashed"),
    ("runner lui-meme a casse", "runner.crashed"),
    ("find its project", "project.no-repo"),
    ("trouve son projet", "project.no-repo"),
    ("read what the ticket says", "notion.read-failed"),
    ("lire ce que dit le ticket", "notion.read-failed"),
    ("nothing here to work from", "ticket.empty"),
    ("rien pour commencer", "ticket.empty"),
    ("kind of ticket", "ticket.kind-unsure"),
    ("type de ce ticket", "ticket.kind-unsure"),
    ("quel type est ce ticket", "ticket.kind-unsure"),
    ("between two types", "ticket.kind-unsure"),
    ("entre deux types", "ticket.kind-unsure"),
)


def _folded(text: str) -> str:
    """Lower case, accents and curly apostrophes set aside: how `_HEARD` is written."""
    bare = unicodedata.normalize("NFD", text.replace("’", "'"))
    return "".join(c for c in bare if not unicodedata.combining(c)).lower()


def classify(sentence: str) -> str:
    """The code a sentence the runner once wrote stands for, `unknown` when none."""
    said = _folded(sentence)
    for fragment, code in _HEARD:
        if fragment in said:
            return code
    return UNKNOWN
