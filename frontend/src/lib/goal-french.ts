/* The French of the badge beside a goal's due date (`goal-deadline.ts`), and of
   what the Goals page says when one is deleted, and of the search
   that ties tickets to a goal in its form (`goal-tickets.tsx`).

   Apart from `french.ts`, as `health-french.ts` is, and fetched by the goal
   cards when they are drawn in French: the first load of a French page is held
   to a budget (tests/test_release.py) it had no room left under, and these are
   words only the Goals page and a project's goals say. Same rule as there: the
   English sentence is the key. */

export const GOAL_FRENCH: Record<string, string> = {
  Late: "En retard",
  "In {{count}} day": "Dans {{count}} jour",
  "In {{count}} days": "Dans {{count}} jours",
  // The way from a goal's page to its tickets on the board.
  "See on the board": "Voir sur le board",
  // What a goal's page says when one is deleted.
  "The goal is deleted. Its tickets stay where they are, and serve no goal. To close a goal that is over, mark it reached or given up instead.":
    "L'objectif est supprimé. Ses tickets restent où ils sont, sans objectif. Pour clore un objectif terminé, marquez-le plutôt atteint ou abandonné.",
  // The search that ties tickets to a goal, in its form.
  "Add a ticket…": "Ajouter un ticket…",
  "Search a ticket...": "Rechercher un ticket…",
  "{{count}} more: narrow the search.": "{{count}} de plus : précisez la recherche.",
  "Finished tickets and other projects too": "Aussi les tickets terminés et ceux des autres projets",
  // A goal's card, while no ticket serves it.
  "No ticket tied yet": "Aucun ticket rattaché",
  "Tie tickets": "Rattacher des tickets",
  "New ticket for this goal": "Nouveau ticket pour cet objectif",
}
