/* The French of a ticket's own view: what its status says it is waiting for,
   and the names its facts are listed under (`ticket-status.tsx`).

   Apart from `french.ts`, as `health-french.ts` is, and fetched by the ticket's
   page when it is drawn in French: the first load of a French page is held to
   a budget (tests/test_release.py), and these are sentences only an opened
   ticket says. A word the board's cards say too stays in `french.ts`. Same
   rule as there: the English sentence is the key. */

export const TICKET_FRENCH: Record<string, string> = {
  "A draft: the runner does not touch it until it is made ready.":
    "Un brouillon : le runner n'y touche pas tant qu'il n'est pas lancé.",
  "Waiting for a free place: a session starts on it by itself.":
    "En attente d'une place libre : une session démarre dessus toute seule.",
  "A session is working on it.": "Une session travaille dessus.",
  "Paused: what was done is kept, and nothing runs until it is resumed.":
    "En pause : ce qui est fait est gardé, et rien ne tourne tant qu'il n'est pas repris.",
  "Stopped: it waits for you to run it again.": "Arrêté : il attend que vous le relanciez.",
  "Your decision is awaited.": "Votre décision est attendue.",
  "Waiting for a decision.": "En attente d'une décision.",
  "Validated: the runner merges its pull request.": "Validé : le runner fusionne sa pull request.",
  "Validated: the runner publishes it at the next free place.":
    "Validé : le runner le publie à la prochaine place libre.",
  "Finished: nothing is left to do.": "Terminé : il ne reste rien à faire.",
  "Given up: nothing runs on it.": "Abandonné : rien ne tourne dessus.",
  "About this ticket": "À propos de ce ticket",
  Creation: "Création",
  Worked: "Travaillé",
  "Last session": "Dernière session",
  Estimate: "Estimation",
  Branch: "Branche",
  "Taken by": "Pris par",
  "Open the session": "Ouvrir la session",
  "This ticket wrote no result of its own: its pull request is the result.":
    "Ce ticket n'a pas écrit de résultat à lui : sa pull request est le résultat.",
  "Status and details": "Statut et détails",
  "Priority, from 0 to 100": "Priorité, de 0 à 100",
  "Change the model": "Changer le modèle",
  "Change the project": "Changer le projet",
  "The model could not be changed": "Le modèle n'a pas pu être changé",
  "Loading…": "Chargement…",
  "set its model to {{model}}": "a mis son modèle à {{model}}",
  "gave it back the runner's model": "lui a rendu le modèle du runner",
  // « Relancer depuis ici » — session-log.tsx, fork-dialog.tsx, ticket-audit.tsx.
  "Start again from here": "Relancer depuis ici",
  "Started again from here": "Relancé depuis ici",
  "current branch": "branche courante",
  "Started again from step {{step}} of session #{{run}}":
    "Relancée depuis l'étape {{step}} de la session #{{run}}",
  "Started again from step {{step}} of an earlier session":
    "Relancée depuis l'étape {{step}} d'une session précédente",
  "Start again from step {{step}}": "Relancer depuis l'étape {{step}}",
  "A new session starts from the conversation up to this step, without what came after it. This session stays readable in the journal.":
    "Une nouvelle session part de la conversation jusqu'à cette étape, sans ce qui a suivi. Cette session-ci reste lisible dans le journal.",
  "The files are not taken back: the worktree and the branch stay as this session left them, with what it changed after this step. The new session is told so, and looks at them first.":
    "Les fichiers ne sont pas remis en arrière : le worktree et la branche restent tels que cette session les a laissés, avec ce qu'elle a changé après cette étape. La nouvelle session en est prévenue et les regarde d'abord.",
  "What the new session is told": "Ce que la nouvelle session reçoit",
  "This time, do it this way… (optional)": "Cette fois, fais plutôt… (facultatif)",
  "Start again": "Relancer",
  "The ticket starts again from step {{step}}": "Le ticket repart de l'étape {{step}}",
  "The ticket could not start again from this step": "Le ticket n'a pas pu repartir de cette étape",
  "started it again from one of its steps": "l'a relancé depuis une de ses étapes",
}
