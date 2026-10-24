/* The French of the badge beside a goal's due date (`goal-deadline.ts`), and of
   what the Goals page says on a board of Markdown files.

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
  // What a goal's page and the empty list say on a board of Markdown files.
  "The goal is deleted: its file goes to the board's trash. Its tickets stay where they are, and serve no goal. To close a goal that is over, mark it reached or given up instead.":
    "L'objectif est supprimé : son fichier part dans la corbeille du board. Ses tickets restent où ils sont, sans objectif. Pour clore un objectif terminé, marquez-le plutôt atteint ou abandonné.",
  "The board has no goals/ folder: add one, and goals can be written here.":
    "Le board n'a pas de dossier goals/ : ajoutez-en un, et les objectifs s'écriront ici.",
}
