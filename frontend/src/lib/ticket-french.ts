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
  "This ticket wrote no result of its own: its pull request, above, is the result.":
    "Ce ticket n'a pas écrit de résultat à lui : sa pull request, ci-dessus, est le résultat.",
}
