/* The console in French.
 *
 * One entry per sentence the console says, keyed by the sentence itself — the
 * key is the English source, so a key nobody has translated is drawn as it was
 * written rather than as a name nobody meant to read. See `i18n.ts`.
 *
 * Three kinds of entry live here, and they are kept apart on purpose:
 *
 * - the words the packages under the console say, which are theirs;
 * - the words the console itself says;
 * - the words `web/settings.py` writes about the configuration, which travel
 *   from the server to the settings page and are translated on arrival. A test
 *   holds that last list to the file it comes from: a setting whose sentence
 *   is rewritten in Python and not here would quietly go back to English.
 *
 * The words, one per thing, the same everywhere:
 *
 * - le tableau de bord — the console's page that draws the board (Dashboard);
 *   « Tableau » (Board) in a phone's bottom bar, where the three words are cut;
 * - le tableau — the board itself, in a sentence: never « board »;
 * - un ticket — a card on it; lancer, relancer — what sends it to the runner;
 * - une récurrence — a ticket that comes back by itself (a schedule);
 * - un objectif — a goal, which tickets are written towards;
 * - un fournisseur — who answers the sessions (a provider);
 * - une session — Claude at work on a ticket, and only that: the strip's count,
 *   a ticket's Execution block, the bell's « Une session attend… »;
 * - une conversation — an exchange with the workspace in the console's drawer;
 *   the page that keeps them is « Conversations », never « Sessions » —
 *   « Chat » in a phone's bottom bar, where « Conversations » is cut.
 */
export const FRENCH: Record<string, string> = {
  /* -- what the packages say ---------------------------------------------- */
  // react-resource-view and react-data-form draw a board, a form and a panel,
  // and say a few things of their own along the way. A word they already say
  // in French is absent from this list: an untranslated key is drawn as it
  // stands, which is the French they were written in.
  "No data yet": "Rien sur le tableau.",
  // What a list with a `noResult` of its own never says — and what the tables
  // in the settings fall back on.
  "No results yet": "Rien pour l'instant",
  "Nothing matched your search. Try different criteria, or come back later.":
    "Rien ne correspond. Changez de critères, ou revenez plus tard.",
  "Nothing here": "rien",
  Saved: "Déplacé",
  create: "Nouveau ticket",
  read: "Ouvrir",
  update: "Modifier",
  Edit: "Modifier",
  delete: "Retirer",
  Cancel: "Annuler",
  Esc: "Échap",
  Enter: "Entrée",
  Delete: "Supprimer",
  "Search...": "Rechercher…",
  "Select...": "Choisir…",
  "Nothing found.": "Rien trouvé.",
  "Nothing found yet": "Rien trouvé pour l'instant",
  "Nothing selected": "Rien de sélectionné",
  "Pick an item from the list to see its details":
    "Choisissez un élément dans la liste pour en voir le détail",
  "View details": "Voir le détail",
  "Clear the search": "Effacer la recherche",
  "This cannot be undone.": "C'est sans retour.",
  "Your changes have been saved": "Vos modifications ont été enregistrées",
  Deleted: "Supprimé",
  "The item has been removed": "L'élément a été supprimé",
  "The item could not be removed": "L'élément n'a pas pu être supprimé",
  "Deletion is not possible": "La suppression est impossible",
  // A value the package prints as it holds it, in the one layout that shows a
  // checkbox without a form around it: the calendar's preview of a schedule.
  true: "oui",
  false: "non",
  /* The calendar, which the schedules are laid out in: the days of its week,
     and the button that walks back through them. `Today`, `Jour`, `Semaine` and
     `Mois` are the package's own French; only what it says in English needs an
     entry here. */
  monday: "lundi",
  tuesday: "mardi",
  wednesday: "mercredi",
  thursday: "jeudi",
  friday: "vendredi",
  saturday: "samedi",
  sunday: "dimanche",
  Previous: "Précédent",
  Today: "Aujourd'hui",
  // The two lines a form ends on, set from `i18n.ts` rather than read from a
  // declaration: they are handed to a toast as they stand.
  // Not `Saved`, which the package already says — and says on a card dropped in
  // another column, where it means "moved".
  Written: "Écrit",
  "Some fields need another look": "Quelques champs demandent une relecture",
  // A table's "Properties" menu, its selection and its pages, a card dragged
  // or moved from the board's selection bar, and what a view says when the
  // server would not answer it: the schedules showed "Properties" in English.
  Properties: "Propriétés",
  "Reset to default": "Revenir au défaut",
  "Select all": "Tout sélectionner",
  "Deselect all": "Tout désélectionner",
  Select: "Sélectionner",
  "Select {{title}}": "Sélectionner {{title}}",
  "Selected records": "Éléments sélectionnés",
  // The package says these with a bare count, whatever it is: the French is
  // turned so that one and many read the same.
  "{{count}} records deleted": "Éléments supprimés : {{count}}",
  "{{failed}} of {{total}} records could not be deleted": "Suppression impossible pour {{failed}} sur {{total}}",
  previous: "Précédent",
  next: "Suivant",
  Move: "Déplacer",
  "Move to…": "Déplacer vers…",
  "Drop here": "Déposer ici",
  "{{count}} cards": "{{count}} cartes",
  "Tickets not tied to the goal: {{count}}": "Tickets non liés à l’objectif : {{count}}",
  "No card could be moved.": "Aucune carte n'a pu être déplacée.",
  "They are back in their column.": "Elles sont revenues dans leur colonne.",
  "{{failed}} of {{total}} cards could not be moved": "Déplacement impossible pour {{failed}} sur {{total}} cartes",
  "Open in full page": "Ouvrir en pleine page",
  "No entries to show over this period.": "Rien à montrer sur cette période.",
  "An error occurred": "Une erreur est survenue",
  "The data could not be loaded": "Les données n'ont pas pu être chargées",
  "The server answered with an error.": "Le serveur a répondu par une erreur.",
  "Access denied": "Accès refusé",
  "You are not allowed to access this page.": "Vous n'avez pas accès à cette page.",
  "The export failed. Please try again.": "L'export a échoué. Réessayez.",

  /* -- where you are ------------------------------------------------------- */
  workspace: "espace de travail",
  live: "en direct",
  schedules: "récurrences",
  settings: "réglages",
  "the console": "la console",
  "the ticket": "le ticket",
  // The bubble in the bottom corner, and what it opens: the ticket's
  // discussion where there is one, the workspace's own everywhere else.
  "Open {{pane}}": "Ouvrir {{pane}}",
  // Ctrl+K, and the button in the bar that opens it.
  "Command palette": "Palette de commandes",
  "Find a page, a project or a ticket, or run an action.":
    "Trouver une page, un projet ou un ticket, ou lancer une action.",
  "Type a page, a project, a ticket…": "Une page, un projet, un ticket…",
  "Nothing matches.": "Rien ne correspond.",
  "Open or close the console": "Ouvrir ou fermer la console",
  Search: "Rechercher",
  "search a page, a project, a ticket": "chercher une page, un projet, un ticket",
  "A sentence talks to your workspace; a line that starts with > runs a command.":
    "Une phrase parle à votre espace de travail ; une ligne qui commence par > lance une commande.",
  "No such page.": "Cette page n'existe pas.",
  "Reading the board…": "Lecture du tableau…",

  /* -- the menu ------------------------------------------------------------ */
  Dashboard: "Tableau de bord",
  Schedules: "Récurrences",
  Settings: "Réglages",
  // On a phone, the entry the bottom bar keeps the other pages behind.
  More: "Plus",
  // A card's own menu, named apart from the bottom bar's « Plus » so a
  // screen reader (and a test) tells the two apart.
  "More actions": "Autres actions",
  "go light": "passer au clair",
  "go dark": "passer au sombre",
  "Switch to the light theme": "Passer au thème clair",
  "Switch to the dark theme": "Passer au thème sombre",
  // The board as the console last read it: when, and what is out of step —
  // the line in the bar, its tooltip, and the button beside it.
  "Resynchronise now": "Resynchroniser maintenant",
  "Notifications, {{count}} unread": "Notifications, {{count}} non lues",
  "{{count}} questions": "{{count}} questions",
  "{{count}} pull requests": "{{count}} pull requests",
  "{{count}} red checks": "{{count}} CI rouges",
  "{{count}} failures": "{{count}} échecs",
  "{{count}} blocks": "{{count}} blocages",
  "what asks for your attention": "ce qui demande votre attention",
  "Mark all as read": "Tout marquer comme lu",
  "Nothing needs you.": "Rien ne demande votre attention.",
  unread: "non lue",
  "A session is waiting for your answer": "Une session attend votre réponse",
  "A pull request is ready to read": "Une pull request est prête à relire",
  "The checks of a pull request fail": "Les vérifications d'une pull request échouent",
  "A session failed": "Une session a échoué",
  "A ticket is blocked": "Un ticket est bloqué",
  "resynchronise now: the whole board read again, the refused moves sent again":
    "resynchroniser maintenant : tout le tableau relu, les déplacements refusés renvoyés",
  "synced {{age}}": "synchro {{age}}",
  "{{count}} s ago": "il y a {{count}} s",
  "last read of the board: {{at}}":
    "dernière lecture du board : {{at}}",
  "whole board compared: {{at}}": "tableau entier comparé : {{at}}",
  "{{count}} gap found and corrected": "{{count}} écart trouvé et corrigé",
  "{{count}} gaps found and corrected": "{{count}} écarts trouvés et corrigés",
  "{{count}} move waiting to be written":
    "{{count}} déplacement en attente d’écriture",
  "{{count}} moves waiting to be written":
    "{{count}} déplacements en attente d’écriture",
  "{{count}} move the board refused":
    "{{count}} déplacement refusé par le board",
  "{{count}} moves the board refused":
    "{{count}} déplacements refusés par le board",
  "{{count}} ticket changed on the board meanwhile":
    "{{count}} ticket modifié sur le board entre-temps",
  "{{count}} tickets changed on the board meanwhile":
    "{{count}} tickets modifiés sur le board entre-temps",
  "the last read failed: {{why}}": "la dernière lecture a échoué : {{why}}",
  // On a card moved from the console, until the board has it — and on the toast
  // that says it once when it will not.
  "waiting to be written to the board":
    "en attente d’écriture sur le board",
  "not written to the board":
    "non écrit sur le board",
  "changed on the board meanwhile — not overwritten":
    "modifié sur le board entre-temps — non écrasé",
  // On a ready card: why it has not been taken yet, when it is not the ordinary wait — see TicketHeld.
  "waiting: scheduled for {{at}}": "en attente : prévu pour le {{at}}",
  "waiting for: {{tickets}}": "attend : {{tickets}}",
  "waiting: out of credit until {{at}}": "en attente : plus de crédit jusqu’à {{at}}",
  "waiting: credit reserve reached until {{at}}": "en attente : réserve de crédit atteinte jusqu’à {{at}}",
  "waiting: today's spending limit reached until {{at}}": "en attente : plafond de dépense du jour atteint jusqu’à {{at}}",
  "waiting: a session is still on it — run again once it ends": "en attente : une session est encore dessus — relancé dès qu’elle se termine",
  "ran it now": "l'a lancé tout de suite",
  "launched it from the assistant": "l'a lancé depuis l'assistant",
  "ran it now, past the limit": "l'a lancé tout de suite, au-delà de la limite",
  "Start it in a free place now, ahead of its turn in the queue.":
    "Le démarrer tout de suite dans une place libre, avant son tour dans la file.",
  "“{{title}}” is starting now": "« {{title}} » démarre maintenant",
  "“{{title}}” was not started": "« {{title}} » n'a pas été lancé",
  "No place is free": "Aucune place n'est libre",
  "{{why}}. Run “{{title}}” anyway, past the limit — one more session at once than the settings allow, this once?":
    "{{why}}. Lancer « {{title}} » quand même, au-delà de la limite — une session de plus en même temps que ce que les réglages permettent, pour cette fois ?",
  "Run it past the limit": "Le lancer au-delà de la limite",
  "All {{count}} places are taken": "Les {{count}} places sont prises",
  "{{project}} already holds its {{count}} places": "{{project}} occupe déjà ses {{count}} places",
  "waiting: --limit reached for this run": "en attente : --limit atteint pour ce lancement",
  "waiting: no daemon is running — nothing takes it": "en attente : aucun démon ne tourne — rien ne le prendra",
  waiting: "en attente",
  "“{{title}}” did not reach the board":
    "« {{title}} » n’est pas arrivé sur le board",
  "“{{title}}” was changed on the board meanwhile":
    "« {{title}} » a été modifié sur le board entre-temps",
  // Why, with the two columns put in (`conflicts.ts`).
  "Ponos wanted to move it to {{wanted}}, but it is {{found}} on the board: left as it is.":
    "Ponos voulait le passer en {{wanted}}, mais il est {{found}} sur le board : laissé tel quel.",
  "You moved it to {{wanted}}, but it is {{found}} on the board: left as it is.":
    "Vous l’aviez passé en {{wanted}}, mais il est {{found}} sur le board : laissé tel quel.",
  "event stream": "flux d'événements",
  "connecting…": "connexion…",
  "reconnecting…": "reconnexion…",
  // The one pill a phone's bar says the stream, the last read and the version in.
  // The menu is a name and a count; the sentences that used to sit under each
  // name are gone, and the words they were made of with them.
  "{{count}} turn": "{{count}} tour",
  "{{count}} turns": "{{count}} tours",
  // At the foot of the menu, where the stream's own dot is: the version, and
  // the one day it matters, that a newer one is waiting. The row of pills it
  // used to be said this beside four other things nobody was reading.
  "the version this console runs": "la version que fait tourner cette console",
  // The day a newer one is waiting, the version is the button that installs
  // it — and the dialog that asks first, then follows the update to the end.
  "Version {{version}} → {{target}}, click to update":
    "Version {{version}} → {{target}}, cliquez pour mettre à jour",
  Update: "Mettre à jour",
  "and {{count}} more": "et {{count}} de plus",
  "Updating…": "Mise à jour…",
  "Install the app": "Installer l'application",
  "Share → Add to Home Screen": "Partager → Sur l'écran d'accueil",
  "New version available": "Nouvelle version, recharger ?",
  "Update failed": "Mise à jour échouée",
  "Home": "Accueil",
  "Update Ponos": "Mettre à jour Ponos",
  "Updating Ponos": "Ponos se met à jour",
  "The update failed": "La mise à jour a échoué",
  "Ponos is up to date": "Ponos est à jour",
  "restarted on {{version}}": "redémarré sur {{version}}",
  "Release notes": "Notes de version",
  "What changed": "Ce qui a changé",
  "Ponos downloads the new version, checks that it starts, then restarts the console. The page reconnects on its own; if anything fails, the current version stays.":
    "Ponos télécharge la nouvelle version, vérifie qu'elle démarre, puis redémarre la console. La page se reconnecte seule ; au moindre échec, la version actuelle reste en place.",
  "A ticket is running": "Un ticket est en cours",
  "The update will start once it has finished: nothing is interrupted, and no ticket starts in between.":
    "La mise à jour partira quand il sera terminé : rien n'est interrompu, et aucun ticket ne démarre entre-temps.",
  "Update now": "Mettre à jour maintenant",
  "Update after the ticket": "Mettre à jour après le ticket",
  "Call it off": "Annuler la mise à jour",
  "The update did not start": "La mise à jour n'a pas démarré",
  "Ponos stayed on its previous version": "Ponos est resté sur sa version précédente",
  "This console cannot update Ponos itself: {{why}}. On the machine it runs on, type:":
    "Cette console ne peut pas mettre Ponos à jour elle-même : {{why}}. Sur la machine où il tourne, tapez :",
  Copy: "Copier",
  "Update scheduled": "Mise à jour programmée",
  "It starts as soon as this is over: {{what}}. No ticket starts in between.":
    "Elle part dès que ceci est terminé : {{what}}. Aucun ticket ne démarre entre-temps.",
  "Starting…": "Démarrage…",
  "Downloading the new version": "Téléchargement de la nouvelle version",
  "Checking that it starts, and installing it": "Vérification qu'elle démarre, et installation",
  "Restarting the console": "Redémarrage de la console",
  "The page reconnects by itself once the new version answers.":
    "La page se reconnecte d'elle-même dès que la nouvelle version répond.",
  Log: "Journal",
  // What the server says it waits for, or why it cannot do it from here
  // (`web/upgrade.py`, `web/api.py`).
  "a ticket is running": "un ticket est en cours",
  "a conversation turn is being answered": "une réponse de la conversation est en cours",
  "a command is running": "une commande est en cours",
  "this is a container: a new version is a new image — docker compose pull && docker compose up -d":
    "c'est un conteneur : une nouvelle version est une nouvelle image — docker compose pull && docker compose up -d",
  "an update is started from the machine the runner is on":
    "une mise à jour se lance depuis la machine où tourne le runner",

  /* -- the board and a ticket ---------------------------------------------- */
  // The columns as the runner names them, for a board that has not named them
  // itself. A board that has is repeated in its own words.
  Ready: "Prêt",
  "In progress": "En cours",
  "In review": "En revue",
  Validated: "Validé",
  Blocked: "Bloqué",
  Failed: "Échoué",
  Done: "Terminé",
  Cancelled: "Abandonné",
  Draft: "Brouillon",
  "Save as draft": "Enregistrer en brouillon",
  "(untitled ticket)": "(ticket sans titre)",
  // The pages of a long list, which the console draws itself (`pagination.tsx`).
  Pagination: "Pagination",
  "Previous page": "Page précédente",
  "Next page": "Page suivante",
  "Showing {{from}} to {{to}} of {{total}} results": "Affichage de {{from}} à {{to}} sur {{total}} résultats",
  "Your board, live. Drop a card in another column and the runner is told.":
    "Votre tableau, en direct. Déposez une carte dans une autre colonne et le runner en est averti.",
  "Nothing on the board yet — a ticket moved to the ready column is a session that starts.":
    "Rien sur le tableau — un ticket déposé dans la colonne prête, c'est une session qui démarre.",
  "New ticket": "Nouveau ticket",
  "New ticket for {{project}}": "Nouveau ticket pour {{project}}",
  Ticket: "Ticket",
  "New ticket for {{name}}": "Nouveau ticket pour {{name}}",
  Title: "Titre",
  "The brief": "Le brief",
  Project: "Projet",
  Status: "Statut",
  Priority: "Priorité",
  Model: "Modèle",
  Cost: "Coût",
  Took: "Durée",
  Scheduled: "Prévu",
  Create: "Créer",
  "What must change, where, and how you will know it is done.":
    "Ce qui doit changer, où, et à quoi vous verrez que c'est fait.",
  "Priority {{score}} out of 100": "Priorité {{score}} sur 100",
  "{{label}}, from 0 to 100": "{{label}}, de 0 à 100",
  "A priority is a number from 0 to 100.": "Une priorité est un nombre de 0 à 100.",
  "0: not important at all · 100: right now. Empty, it is 50.":
    "0 : vraiment pas important · 100 : tout de suite. Vide, c'est 50.",
  "deduced by the runner": "déduit par le runner",
  "The road the ticket takes. Empty, the runner deduces it before the ticket runs.":
    "Le chemin que prend le ticket. Vide, le runner le déduit avant de le lancer.",
  "the runner's model": "le modèle du runner",
  "The runner's model": "Le modèle du runner",
  "no project — a document": "aucun projet — un document",
  // The "New ticket" dialog, in two columns (new-ticket.tsx).
  "Markdown · read by the runner on the ticket's page": "Markdown · lu par le runner sur la page du ticket",
  "Done criterion": "Critère de fin",
  "File concerned": "Fichier concerné",
  "It is done when": "C'est fait quand",
  "what you will see once it is done": "ce que vous verrez une fois que c'est fait",
  "Files concerned": "Fichiers concernés",
  "path/to/the/file": "chemin/du/fichier",
  Auto: "Auto",
  "A git repository: the ticket comes back as a pull request.":
    "Un dépôt git : le ticket revient en pull request.",
  "No repository: the ticket comes back as a document.": "Pas de dépôt : le ticket revient en document.",
  "no git": "sans git",
  "The runner deduces the commit prefix and the CHANGELOG section.":
    "Le runner déduit le préfixe du commit et la section du CHANGELOG.",
  "Launched, the ticket starts as soon as a place is free.": "Lancé, le ticket démarre dès qu'une place se libère.",
  "Launched, the ticket starts once the daemon runs.": "Lancé, le ticket démarre dès que le démon tourne.",
  "Launch the ticket": "Lancer le ticket",
  "no project": "aucun projet",
  "Open the project {{name}}": "Ouvrir le projet {{name}}",
  "pull request": "pull request",
  session: "session",
  "just now": "à l'instant",
  "{{count}} min ago": "il y a {{count}} min",
  "{{count}}h ago": "il y a {{count}} h",
  "{{count}}d ago": "il y a {{count}} j",
  "{{count}}mo ago": "il y a {{count}} mois",
  "Scroll to the last message": "Aller au dernier message",
  "{{count}} min": "{{count}} min",
  "{{count}} h": "{{count}} h",
  "Run again": "Relancer",
  // Why a ticket stopped (blocks.py), on its card, in the search and in the statistics.
  Answer: "Répondre",
  "See the pull request": "Voir la pull request",
  "See the base's CI": "Voir la CI de la base",
  Cause: "Cause",
  "Blocks, by cause and week": "Blocages, par cause et par semaine",
  "Show more": "Voir plus",
  "Show less": "Voir moins",
  "No ticket stopped in the period.": "Aucun ticket arrêté sur la période.",
  "week of {{day}}": "semaine du {{day}}",
  // A code ticket's sub-type (subtypes.py): its badge, its filter, its field and its statistics.
  "sub-type": "sous-type",
  "What kind of change a code ticket is: the prefix of its commit and its CHANGELOG section. Empty, the runner deduces it.":
    "La nature du changement d'un ticket Code : le préfixe de son commit et sa section du CHANGELOG. Vide, le runner la déduit.",
  "Done, by sub-type and week": "Terminés, par sous-type et par semaine",
  "No code ticket with a sub-type closed in the period.": "Aucun ticket Code avec un sous-type terminé sur la période.",
  "Average cost": "Coût moyen",
  "Average duration": "Durée moyenne",
  Merge: "Fusion",
  Infrastructure: "Infrastructure",
  Question: "Question",
  "Make ready": "Lancer",
  "Validate and publish": "Valider et publier",
  "Run the agent again": "Relancer l'agent",
  "Mark done": "Marquer terminé",
  "Cancel the ticket": "Abandonner le ticket",
  Reopen: "Rouvrir",
  "Back to the drafts: the runner does not touch it until it is made ready.":
    "Retour aux brouillons : le runner n'y touche pas tant qu'il n'est pas lancé.",
  validate: "valider",
  done: "terminé",
  hold: "mettre en attente",
  project: "projet",
  priority: "priorité",
  model: "modèle",
  type: "type",
  default: "par défaut",
  "Claude Code's default, unknown before the first session":
    "défaut de Claude Code, inconnu avant la première session",
  spent: "dépensé",
  took: "durée",
  time: "temps",
  "{{minutes}} min {{seconds}} s": "{{minutes}} min {{seconds}} s",
  "{{count}} s": "{{count}} s",
  "{{hours}} h {{minutes}}": "{{hours}} h {{minutes}}",
  "<1 min": "< 1 min",
  "On hold: waiting for your answer": "En pause : en attente de votre réponse",
  "On hold: the ticket is blocked": "En pause : le ticket est bloqué",
  "On hold: waiting for credit": "En pause : en attente de crédits",
  "Working time": "Temps de travail",
  "≈ {{cost}} · {{time}}, up to {{high}}": "≈ {{cost}} · {{time}}, jusqu’à {{high}}",
  "Estimated from {{count}} similar tickets: the median, and the 80th centile":
    "Estimé d’après {{count}} tickets comparables : la médiane, et le 80e centile",
  "Time on hold": "Temps en pause",
  Sessions: "Sessions",
  "taken by": "pris par",
  worked: "travaillé",
  "last session {{time}}": "dernière session : {{time}}",
  created: "créé",
  scheduled: "prévu",
  "the brief": "le brief",
  Brief: "Brief",
  "The brief could not be read": "Le brief n'a pas pu être lu",
  "The brief is saved": "Le brief est enregistré",
  "The next ticket of this project is told this.":
    "Le prochain ticket de ce projet en prend connaissance.",
  "The brief was not saved": "Le brief n'a pas été enregistré",
  "This brief changed on the board since you opened it.":
    "Ce brief a changé sur le board depuis l'ouverture de l'éditeur.",
  "Saving would overwrite that. Reload it to see the new version — what you typed here is dropped.":
    "Enregistrer l'écraserait. Rechargez-le pour voir la nouvelle version — ce que vous avez saisi ici est abandonné.",
  Reload: "Recharger",
  "Saving rewrites the page from this text. The page holds what Markdown cannot keep, and it will be lost:":
    "Enregistrer réécrit la page à partir de ce texte. La page contient ce que le Markdown ne sait pas garder, et cela sera perdu :",
  "Save and lose these?": "Enregistrer et perdre ceci ?",
  "Save anyway": "Enregistrer quand même",
  "Leave without saving?": "Quitter sans enregistrer ?",
  "The changes made to this brief are not saved.":
    "Les modifications de ce brief ne sont pas enregistrées.",
  "Keep editing": "Continuer à modifier",
  Leave: "Quitter",
  "bold, italic and colours": "gras, italique et couleurs",
  links: "liens",
  mentions: "mentions",
  equations: "équations",
  toggles: "blocs dépliables",
  callouts: "encadrés",
  tables: "tableaux",
  columns: "colonnes",
  "sub-pages": "sous-pages",
  "embedded databases": "bases de données incrustées",
  images: "images",
  files: "fichiers",
  "PDFs": "PDF",
  bookmarks: "signets",
  embeds: "contenus incrustés",
  "blocks nested too deep": "blocs imbriqués trop profondément",
  Live: "En direct",
  "Unfold everything": "Tout déplier",
  "Fold everything": "Tout replier",
  "Getting ready": "Préparation",
  "Before these lines": "Avant ces lignes",
  "The page is empty: the title is the whole brief.":
    "La page est vide : le titre est tout le brief.",
  Mission: "Mission",
  "What was done": "Ce qui a été fait",
  "Nothing yet: Ponos writes this part at the end of every session.":
    "Rien encore : Ponos écrit cette partie à la fin de chaque session.",
  "This ticket could not be read.": "Ce ticket n'a pas pu être lu.",
  "Ticket created": "Ticket créé",
  "could not move the ticket": "impossible de déplacer le ticket",
  "The ticket could not be created": "Le ticket n'a pas pu être créé",
  "not written": "message non écrit",
  "Not saved": "Non enregistré",
  "The command was not run": "La commande n'a pas été lancée",
  "The message was not sent": "Le message n'a pas été envoyé",
  "could not move “{{title}}”": "impossible de déplacer « {{title}} »",
  "“{{title}}” moved to {{column}}": "« {{title}} » déplacé dans {{column}}",
  Resume: "Reprendre",
  "Set aside": "Mettre de côté",
  "The runner no longer touches it, until it is made ready again.":
    "Le runner n'y touche plus, jusqu'à ce qu'il soit remis prêt.",
  "Run “{{title}}” again?": "Relancer « {{title}} » ?",
  "The ticket goes back to {{column}} and a new session starts on it as soon as a place is free — a session that is paid for, like the first one.":
    "Le ticket retourne dans {{column}} et une nouvelle session démarre dessus dès qu'une place se libère — une session payante, comme la première.",
  "Run it again": "Relancer",
  "Make “{{title}}” ready?": "Rendre « {{title}} » prêt ?",
  "The ticket goes to {{column}} and a session starts on it as soon as a place is free — a session that is paid for.":
    "Le ticket passe dans {{column}} et une session démarre dessus dès qu'une place se libère — une session payante.",
  "Its validation is withdrawn: the runner will not merge or publish it.":
    "Sa validation est annulée : le runner ne le fusionnera ni ne le publiera.",
  "Make it ready": "Lancer le ticket",
  // The board's selection, and the bar that acts on it (`bulk-bar.tsx`).
  "Select “{{title}}”": "Sélectionner « {{title}} »",
  "Select the column “{{column}}”": "Sélectionner la colonne « {{column}} »",
  "Selected tickets": "Tickets sélectionnés",
  "{{count}} ticket selected": "{{count}} ticket sélectionné",
  "{{count}} tickets selected": "{{count}} tickets sélectionnés",
  "Clear the selection": "Vider la sélection",
  "The runner no longer touches them, until they are made ready again.":
    "Le runner n'y touche plus, jusqu'à ce qu'ils soient remis prêts.",
  "{{count}} ticket set aside": "{{count}} ticket mis de côté",
  "{{count}} tickets set aside": "{{count}} tickets mis de côté",
  "{{count}} ticket launched": "{{count}} ticket lancé",
  "{{count}} tickets launched": "{{count}} tickets lancés",
  "{{count}} ticket given up": "{{count}} ticket abandonné",
  "{{count}} tickets given up": "{{count}} tickets abandonnés",
  "Priority, from 0 to 100": "Priorité, de 0 à 100",
  Apply: "Appliquer",
  "The priority could not be changed": "La priorité n'a pas pu être changée",
  "{{count}} ticket ranked": "Priorité changée sur {{count}} ticket",
  "{{count}} tickets ranked": "Priorité changée sur {{count}} tickets",
  "{{count}} ticket pointed at the goal": "{{count}} ticket rattaché à l'objectif",
  "{{count}} tickets pointed at the goal": "{{count}} tickets rattachés à l'objectif",
  "{{count}} ticket serves no goal": "{{count}} ticket ne sert plus aucun objectif",
  "{{count}} tickets serve no goal": "{{count}} tickets ne servent plus aucun objectif",
  "Give up": "Abandonner",
  "Launch {{count}} ticket?": "Lancer {{count}} ticket ?",
  "Launch {{count}} tickets?": "Lancer {{count}} tickets ?",
  "Launch {{count}} ticket": "Lancer {{count}} ticket",
  "Launch {{count}} tickets": "Lancer {{count}} tickets",
  "They go to {{column}} and a session starts on each as places free — sessions that are paid for.":
    "Ils passent dans {{column}} et une session démarre sur chacun à mesure que les places se libèrent — des sessions payantes.",
  "Estimated cost: ≈ {{cost}}, up to {{high}}": "Coût estimé : ≈ {{cost}}, jusqu'à {{high}}",
  "No estimate yet: too few tickets like these have run.":
    "Pas encore d'estimation : trop peu de tickets semblables ont tourné.",
  "{{count}} of them has no estimate and is not counted.":
    "{{count}} d'entre eux n'a pas d'estimation et n'est pas compté.",
  "{{count}} of them have no estimate and are not counted.":
    "{{count}} d'entre eux n'ont pas d'estimation et ne sont pas comptés.",
  "Give up {{count}} ticket?": "Abandonner {{count}} ticket ?",
  "Give up {{count}} tickets?": "Abandonner {{count}} tickets ?",
  "Give up {{count}} ticket": "Abandonner {{count}} ticket",
  "Give up {{count}} tickets": "Abandonner {{count}} tickets",
  "They go to {{column}}: the runner no longer touches them. Each one can be reopened from its card.":
    "Ils passent dans {{column}} : le runner n'y touche plus. Chacun se rouvre depuis sa carte.",
  "Validate “{{title}}”?": "Valider « {{title}} » ?",
  "The runner merges its pull request right away. A merge is not taken back from here.":
    "Le runner fusionne sa pull request tout de suite. Une fusion ne se défait pas d'ici.",
  "The runner publishes what the ticket holds at the next free place.":
    "Le runner publie le contenu du ticket à la prochaine place libre.",
  "Retry the merge": "Réessayer la fusion",
  "Retry the merge of “{{title}}”?": "Réessayer la fusion de « {{title}} » ?",
  "No session is started: the ticket goes back to {{column}}, and the runner merges its pull request as soon as its checks are green. A merge is not taken back from here.":
    "Aucune session n'est lancée : le ticket retourne dans {{column}}, et le runner fusionne sa pull request dès que sa CI est verte. Une fusion ne se défait pas d'ici.",
  "Back to review": "Renvoyer en revue",
  "Back to {{column}}, to be decided on again: nothing is merged, and no session is started.":
    "De retour dans {{column}}, pour en décider à nouveau : rien n'est fusionné, et aucune session n'est lancée.",
  Validate: "Valider",
  "Try again": "Réessayer",
  "Back to the board": "Retour au tableau",
  "The server gave no reason.": "Le serveur n'a pas donné de raison.",
  "This ticket could not be found.": "Ce ticket est introuvable.",
  "This ticket does not exist: it was deleted, or was never on this board.":
    "Ce ticket n'existe pas : il a été supprimé, ou n'a jamais été sur ce board.",
  "A ticket needs a title.": "Un ticket a besoin d'un titre.",
  "Remove the banner from the dashboard": "Retirer le bandeau du tableau de bord",
  "Earlier columns": "Colonnes précédentes",
  "More columns": "Colonnes suivantes",
  "{{count}} empty column hidden": "{{count}} colonne vide masquée",
  "{{count}} empty columns hidden": "{{count}} colonnes vides masquées",
  "Hide empty columns": "Masquer les colonnes vides",
  "Show them": "Les afficher",
  "Show more ({{count}} left)": "Voir plus ({{count}} restants)",
  "The board could not be read again": "Le tableau n'a pas pu être relu",
  "Board read again": "Tableau relu",
  "Map a project to a folder": "Associer un projet à un dossier",
  "A schedule written here is a ticket that comes back on its own.":
    "Une récurrence écrite ici est un ticket qui revient tout seul.",
  Close: "Fermer",
  Link: "Lien",
  "daemon switched off — ponos service on": "démon arrêté — ponos service on",
  "daemon not installed — ponos service on": "démon non installé — ponos service on",
  "daemon masked in systemd": "démon masqué dans systemd",
  "daemon stopped on an error — ponos service on": "démon arrêté sur une erreur — ponos service on",
  "no daemon — ponos daemon": "aucun démon — ponos daemon",
  "daemon stopped — ponos service on": "démon arrêté — ponos service on",
  "daemon state unknown": "état du démon inconnu",
  "daemon {{state}}": "démon {{state}}",

  /* -- the search over the board and a project's tickets ------------------- */
  "Search tickets: title, id, result, pull request…":
    "Chercher un ticket : titre, id, résultat, pull request…",
  "Search tickets": "Chercher un ticket",
  Filters: "Filtres",
  Clear: "Effacer",
  Period: "Période",
  "Created or changed": "Créé ou modifié",
  "Any time": "N'importe quand",
  "Last 7 days": "7 derniers jours",
  "Last 30 days": "30 derniers jours",
  "With a pull request": "Avec une pull request",
  "Waiting for credits": "En attente de crédits",
  "Move not synced": "Déplacement non synchronisé",
  "Any cost": "Tout coût",
  Other: "Autres",
  "More than {{amount}}": "Plus de {{amount}}",
  "No ticket matches": "Aucun ticket ne correspond",
  "Other words, or fewer filters, and they will be back.":
    "D'autres mots, ou moins de filtres, et ils reviendront.",
  "Clear the filters": "Effacer les filtres",
  "No project matches": "Aucun projet ne correspond",
  "Other words, or another type, and they will be back.":
    "D'autres mots, ou un autre type, et ils reviendront.",
  "Search a project": "Chercher un projet",
  "All types": "Tous les types",
  "No type": "Sans type",

  /* -- a ticket's terminal -------------------------------------------------- */
  Discussion: "Discussion",
  "a question is waiting for you": "une question vous attend",
  "waiting for you": "vous attend",
  "CI running": "CI en cours",
  "CI passed": "CI réussie",
  "CI failed": "CI en erreur",
  "Checks on GitHub": "Checks sur GitHub",
  "CI retry {{n}}/{{limit}}": "Reprise CI {{n}}/{{limit}}",
  "At the last pass, on {{at}}: {{said}}": "Au dernier passage, le {{at}} : {{said}}",
  "At the last pass: {{said}}": "Au dernier passage : {{said}}",
  "Nothing has been said on this ticket yet.": "Rien n'a encore été dit sur ce ticket.",
  "This looks like a password or a token. Nothing was sent: remove it, or send again and it will be masked before it reaches the ticket.":
    "Ceci ressemble à un mot de passe ou à un token. Rien n'a été envoyé : retirez-le, ou renvoyez le message et il sera masqué avant d'arriver sur le ticket.",
  "reading the discussion…": "lecture de la discussion…",
  "an answer to its question runs it again": "une réponse à sa question le relance",
  "asks it for words instead": "lui demande des mots plutôt que du travail",
  "read the discussion again": "relire la discussion",
  "Reading…": "Lecture…",
  "not written: {{why}}": "non écrit : {{why}}",
  "could not read the discussion: {{why}}": "impossible de lire la discussion : {{why}}",
  you: "vous",
  problem: "problème",
  command: "commande",

  /* -- the workspace console ------------------------------------------------ */
  "Ask the workspace, or type >status": "Demandez à l'espace de travail, ou tapez >status",
  "Ask me anything about your workspace — I can read your repositories, look at the board and create tickets. Type > followed by a command (>status, >list, >doctor) to use the CLI directly.":
    "Demandez-moi ce que vous voulez sur votre espace de travail — je peux lire vos dépôts, regarder le tableau et créer des tickets. Tapez > suivi d'une commande (>status, >list, >doctor) pour passer directement par le CLI.",
  Send: "Envoyer",
  "Start a new conversation": "Démarrer une nouvelle conversation",
  "exit {{code}}": "sortie {{code}}",
  "Full screen": "Plein écran",
  "Leave full screen": "Quitter le plein écran",
  "Resize the drawer": "Redimensionner le panneau",
  Copied: "Copié",
  "Copy impossible: select the text": "Copie impossible : sélectionnez le texte",
  "Copy the full id": "Copier l’id complet",
  "Open the full page": "Ouvrir en page complète",
  "{{count}} launches · {{name}}": "{{count}} lancements · {{name}}",
  "Last launch: it has happened.": "Dernier lancement : il a eu lieu.",
  "Due: not born yet.": "À venir : pas encore lancé.",
  "Open the schedule": "Ouvrir la récurrence",
  "Open the schedule's page on the board": "Ouvrir la page de la récurrence sur le tableau",
  "Drop to attach to your message": "Déposez pour joindre à votre message",
  "Photos, videos and documents, up to {{limit}} MB each":
    "Photos, vidéos et documents, jusqu'à {{limit}} Mo chacun",

  /* -- the message bar ------------------------------------------------------- */
  "Attach a file": "Joindre un fichier",
  "Attach a photo, a video or a document — or drop it, or paste it":
    "Joindre une photo, une vidéo ou un document — ou le déposer, ou le coller",
  "Remove {{name}}": "Retirer {{name}}",
  "Open {{name}}": "Ouvrir {{name}}",
  "A file sent to the workspace": "Un fichier envoyé à l'espace de travail",
  "“{{name}}” is over {{limit}} MB": "« {{name}} » dépasse {{limit}} Mo",
  "“{{name}}” is not a file the workspace can take":
    "« {{name}} » n'est pas un fichier que l'espace de travail accepte",
  "The limit is web.attachment_max_mb, in the settings.":
    "La limite est web.attachment_max_mb, dans les paramètres.",
  "Images (png, jpg, webp, gif), videos (mp4, webm, mov) and documents (pdf, txt, md, csv, json, docx, xlsx).":
    "Images (png, jpg, webp, gif), vidéos (mp4, webm, mov) et documents (pdf, txt, md, csv, json, docx, xlsx).",
  "“{{name}}” could not be attached": "« {{name}} » n'a pas pu être joint",
  Commands: "Commandes",
  Dictate: "Dicter",
  Recording: "Enregistrement",
  "Voice mode": "Mode vocal",
  "Leave voice mode": "Quitter le mode vocal",
  "Listening…": "J'écoute…",
  "Speaking…": "Je parle…",
  Interrupt: "Interrompre",
  Listen: "Écouter",
  "Stop listening": "Arrêter la lecture",
  "The answer could not be read aloud": "La réponse n'a pas pu être lue à voix haute",
  "The voice could not speak": "La voix n'a pas pu parler",
  "The voice is not available": "La voix n'est pas disponible",
  "Voice is off: speech.enabled is false": "La voix est désactivée : speech.enabled est faux",
  "Voice needs Piper: run `ponos extras add voice`":
    "La voix demande Piper : lancez `ponos extras add voice`",
  "Install the voice": "Installer la voix",
  "Installing the voice…": "Installation de la voix…",
  "The voice is installed": "La voix est installée",
  "The voice could not be installed": "La voix n'a pas pu être installée",
  "Transcribing…": "Transcription…",
  Stop: "Arrêter",
  "The workspace is answering": "L'espace de travail répond",
  // The Stop the arrow becomes while a turn runs, and what a stopped turn says.
  "Stopping…": "Arrêt en cours…",
  // Said while Ponos answers: the message waits, and can be changed or taken back.
  "Send — it waits for Ponos to finish": "Envoyer — le message attend la fin de la réponse de Ponos",
  "Edit the waiting message": "Modifier le message en attente",
  "Remove the waiting message": "Retirer le message en attente",
  "1 message is waiting. Send it, or throw it away?":
    "1 message est en attente. L'envoyer, ou le jeter ?",
  "{{count}} messages are waiting. Send them, or throw them away?":
    "{{count}} messages sont en attente. Les envoyer, ou les jeter ?",
  "Throw the waiting message away?": "Jeter le message en attente ?",
  "Throw the {{count}} waiting messages away?": "Jeter les {{count}} messages en attente ?",
  "They are not sent, and cannot be brought back.": "Ils ne sont pas envoyés, et ne pourront pas être récupérés.",
  "Messages discarded": "Messages jetés",
  "The waiting messages could not be sent": "Les messages en attente n'ont pas pu être envoyés",
  "The waiting messages could not be discarded": "Les messages en attente n'ont pas pu être jetés",
  "The waiting message could not be changed": "Le message en attente n'a pas pu être modifié",
  "The waiting message could not be removed": "Le message en attente n'a pas pu être retiré",
  Discard: "Jeter",
  "stopped by you": "interrompu par vous",
  "answered in {{time}}": "répondu en {{time}}",
  "after {{time}}": "au bout de {{time}}",
  // Brand Assets' chat kit, in `components/chat`: the words it said in French
  // only, in the French it said them in.
  Conversation: "Conversation",
  "Last message": "Dernier message",
  You: "Vous",
  Assistant: "Assistant",
  Thinking: "Réflexion",
  "Thinking…": "Réflexion en cours…",
  Waiting: "En attente",
  Running: "En cours",
  "Approval needed": "Validation requise",
  Denied: "Refusé",
  "Approval of the tool {{name}}": "Validation de l'outil {{name}}",
  "The assistant asks to use": "L'assistant demande à utiliser",
  Deny: "Refuser",
  Approve: "Approuver",
  "Arguments of {{name}}": "Arguments de {{name}}",
  Result: "Résultat",
  "Result of {{name}}": "Résultat de {{name}}",
  "Result of the tool": "Résultat de l'outil",
  // Ponos, while the workspace answers: one line about the last step. See `thinking.ts`.
  "thinking…": "réfléchit…",
  "stopping…": "s'arrête…",
  "reading {{name}}…": "lit {{name}}…",
  "reading a file…": "lit un fichier…",
  "editing {{name}}…": "modifie {{name}}…",
  "editing a file…": "modifie un fichier…",
  "writing {{name}}…": "écrit {{name}}…",
  "writing a file…": "écrit un fichier…",
  "searching the code…": "cherche dans le code…",
  "looking it up on the web…": "cherche sur le web…",
  "handing part of it to a helper…": "confie une partie à un assistant…",
  "planning the work…": "planifie le travail…",
  "fixing an error…": "corrige une erreur…",
  "looking at the board…": "regarde le tableau…",
  "looking at the history…": "regarde l'historique…",
  "running the tests…": "lance les tests…",
  "running a command…": "lance une commande…",
  // The title of a step — lib/thinking.ts, `named`.
  "I read the project’s code": "Je lis le code du projet",
  "I edit the project’s files": "Je modifie les fichiers du projet",
  "I write a file": "J’écris un fichier",
  "I search the project’s code": "Je cherche dans le code du projet",
  "I look for information on the web": "Je cherche des informations sur le web",
  "I hand part of the work to a helper": "Je confie une partie du travail à un assistant",
  "I plan the work": "Je planifie le travail",
  "Something went wrong": "Quelque chose s’est mal passé",
  "I save and send the changes": "J’enregistre et j’envoie les modifications",
  "I check that everything works": "Je vérifie que tout fonctionne",
  "I look at the scheduled tasks": "Je consulte les tâches planifiées",
  "I look at the board": "Je consulte le tableau",
  "I look at the project’s history": "Je consulte l’historique du projet",
  "I install what the project needs": "J’installe ce dont le projet a besoin",
  "I check that the project builds": "Je vérifie que le projet se construit",
  "I look through the project’s files": "Je parcours les fichiers du projet",
  "I work on the project": "Je travaille sur le projet",
  "Called with": "Appelé avec",
  "See more": "Voir plus",
  "working…": "travaille…",
  // The steps of a turn, as a timeline of cards.
  "Show the steps": "Voir les étapes",
  "Hide the steps": "Masquer les étapes",
  "Expand all": "Tout déplier",
  "Collapse all": "Tout replier",
  "{{count}} step went wrong": "{{count}} étape en erreur",
  "{{count}} steps went wrong": "{{count}} étapes en erreur",
  "Dictation is not available": "La dictée n'est pas disponible",
  "Dictation is transcribed by OpenRouter: add an OpenRouter key in the settings":
    "La dictée est transcrite par OpenRouter : ajoutez une clé OpenRouter dans les paramètres",
  "This browser gives the page no microphone": "Ce navigateur ne donne aucun micro à la page",
  "The microphone is blocked for this page — allow it in the browser's site settings":
    "Le micro est bloqué pour cette page — autorisez-le dans les paramètres du site du navigateur",
  "The microphone could not be opened": "Le micro n'a pas pu être ouvert",
  "Nothing was heard": "Rien n'a été entendu",
  "The recording could not be transcribed": "L'enregistrement n'a pas pu être transcrit",

  /* -- a ticket's session, and the runner's figures ----------------------------- */
  "writing now": "en train d'écrire",
  "the last session, read-only": "la dernière session, en lecture seule",
  "an earlier session, read-only": "une session précédente, en lecture seule",
  "This run wrote no step.": "Ce passage n'a écrit aucune étape.",
  "Earlier steps": "Étapes précédentes",
  "The earlier steps could not be read": "Les étapes précédentes n'ont pas pu être lues",
  Run: "Passage",
  "going on": "en cours",
  blocked: "bloqué",
  failed: "échoué",
  validated: "validé",
  "waiting for credit": "en attente de crédit",
  "Follow the session": "Suivre la session",
  "starting…": "démarrage…",
  "no step from the session yet": "la session n'a encore rien écrit",
  "for {{span}}": "depuis {{span}}",
  "rebasing onto {{base}}": "rebase sur {{base}}",
  rebasing: "rebase en cours",
  "running the CI here": "lance la CI en local",
  "reviewing the diff against the ticket": "relit le diff contre le ticket",
  "waiting for the CI of PR #{{number}}": "attend la CI de la PR #{{number}}",
  "waiting for the CI of the pull request": "attend la CI de la PR",
  "fixing the CI of PR #{{number}}": "répare la CI de la PR #{{number}}",
  "fixing the CI": "répare la CI",
  "resolving the conflicts with {{base}}": "résout les conflits avec {{base}}",
  "resolving the conflicts": "résout les conflits",
  "The session has not written anything yet. Its first step appears here as it happens.":
    "La session n'a encore rien écrit. Sa première étape apparaît ici dès qu'elle a lieu.",
  "No journal is left for this ticket: its session log is gone, or it never ran.":
    "Il ne reste aucun journal pour ce ticket : son journal de session a disparu, ou il n'a jamais tourné.",
  sessions: "sessions",
  "{{count}} ticket in progress": "{{count}} ticket en cours",
  "{{count}} tickets in progress": "{{count}} tickets en cours",
  "nothing in progress": "rien en cours",
  places: "places",
  off: "arrêté",
  "nothing waits": "rien n'attend",
  "The daemon's places and its queue": "Les places du démon et sa file d'attente",
  "{{busy}} of {{width}} places taken": "{{busy}} place(s) prise(s) sur {{width}}",
  "the answers to comments": "les réponses aux commentaires",
  "every place is free": "toutes les places sont libres",
  "By project": "Par projet",
  "{{project}}: {{busy}} of {{limit}}": "{{project}} : {{busy}} sur {{limit}}",
  "{{count}} ticket waiting": "{{count}} ticket en attente",
  "{{count}} tickets waiting": "{{count}} tickets en attente",
  "every place is taken": "toutes les places sont prises",
  "its project is at its limit": "son projet est à sa limite",
  "waits for {{tickets}}": "attend {{tickets}}",
  "not before {{at}}": "pas avant {{at}}",
  "out of credit": "plus de crédit",
  "the credit reserve is reached": "la réserve de crédit est atteinte",
  handled: "traités",
  "{{amount}} spent so far": "{{amount}} dépensés jusqu'ici",
  "{{count}} step": "{{count}} étape",
  "{{count}} steps": "{{count}} étapes",
  "Out of credit until {{at}}. The subscription's window is spent: tickets stay where they are, and the first run after that takes them again.":
    "Crédits épuisés jusqu'à {{at}}. La fenêtre de l'abonnement est consommée : les tickets restent où ils sont, et la première passe après ce moment les reprend.",
  "Today's spending limit is reached: {{spent}} spent, limit {{limit}}. Ready tickets wait, and nothing new starts before midnight.":
    "Le plafond de dépense du jour est atteint : {{spent}} dépensés, plafond {{limit}}. Les tickets prêts attendent, et rien de nouveau ne démarre avant minuit.",
  "`claude` was not found on this machine: no session can start.":
    "`claude` est introuvable sur cette machine : aucune session ne peut démarrer.",

  /* -- what comes back on its own -------------------------------------------- */
  /* `Cadence`, `Model` and `Priority` are already said above, where the
     configuration says them; `table` is said where the board says it. */
  Schedule: "Récurrence",
  Calendar: "Calendrier",
  "A row says what to make and how often; when the moment comes the runner writes the ticket into the ready column and steps back.":
    "Une ligne dit quoi faire et à quelle fréquence ; le moment venu, le runner écrit le ticket dans la colonne prête et se retire.",
  "{{count}} of {{total}} on": "{{count}} active sur {{total}}",
  // The four cadences, as the list and the select draw them: the board keeps
  // the English word, which is the one `schedules.py` reads.
  Hourly: "Toutes les heures",
  Daily: "Quotidienne",
  Weekly: "Hebdomadaire",
  Monthly: "Mensuelle",
  paused: "en pause",
  "nothing yet": "rien pour l'instant",
  "Nothing repeats here": "Rien ne se répète ici",
  "This board keeps no schedules.": "Ce tableau ne garde pas de récurrences.",
  "Nothing repeats here yet": "Rien ne se répète encore ici",
  "Nothing repeats for this project yet": "Rien ne se répète encore pour ce projet",
  "Other words or another state, and they will be back.": "D'autres mots ou un autre état, et elles reviendront.",
  "A schedule made here makes its tickets for this project.": "Une récurrence créée ici crée ses tickets pour ce projet.",
  "See every goal of the project": "Voir tous les objectifs du projet",
  "This project has no page: create it to attach tickets to it.":
    "Ce projet n'a pas de page : créez-la pour y rattacher des tickets.",
  "Create its page": "Créer sa page",
  "This schedule is no longer on the board.": "Cette récurrence n'est plus sur le tableau.",
  // The columns of the list, and the fields of the form that writes a row.
  Day: "Jour",
  On: "Active",
  Next: "Prochaine",
  Last: "Dernière",
  Problem: "Problème",
  Rule: "Règle",
  "{{name}} on": "{{name}} active",
  "The schedule could not be saved": "La récurrence n'a pas pu être enregistrée",
  // The search over the list, as the projects have theirs.
  "Search a schedule": "Chercher une récurrence",
  "On or paused": "Actives et en pause",
  on: "active",
  "No schedule matches": "Aucune récurrence ne correspond",
  "Other words, another project or another state, and they will be back.":
    "D'autres mots, un autre projet ou un autre état, et elles reviendront.",
  "New schedule": "Nouvelle récurrence",
  // The window a schedule is written in (see `recurrence-dialog.tsx`).
  "New recurring ticket": "Nouvelle récurrence",
  "Edit the schedule": "Modifier la récurrence",
  "Ponos creates this ticket automatically, at the cadence you choose.":
    "Ponos crée ce ticket automatiquement, à la cadence choisie.",
  "Ticket title": "Titre du ticket",
  "Weekly dependency review": "Revue hebdomadaire des dépendances",
  "A schedule needs a name": "Une récurrence a besoin d'un nom",
  "When?": "Quand ?",
  "Every hour": "Chaque heure",
  "Every day": "Chaque jour",
  "Every week": "Chaque semaine",
  "Every month": "Chaque mois",
  Time: "Heure",
  "On the": "Le",
  "of the month": "du mois",
  "Every hour at :{{minute}}": "Chaque heure à :{{minute}}",
  "Every day at {{time}}": "Chaque jour à {{time}}",
  "Every week at {{time}}": "Chaque semaine à {{time}}",
  "Every {{day}} at {{time}}": "Chaque {{day}} à {{time}}",
  "On day {{day}} of every month at {{time}}": "Le {{day}} de chaque mois à {{time}}",
  "{{date}} at {{time}}": "{{date}} à {{time}}",
  "at the next look at the board": "au prochain relevé du tableau",
  "Next ticket: {{when}}.": "Prochain ticket : {{when}}.",
  "Next ticket, once it is turned on: {{when}}.": "Prochain ticket, une fois activée : {{when}}.",
  "Choose a cadence and an hour to see when the next ticket is created.":
    "Choisissez une cadence et une heure pour voir quand le prochain ticket sera créé.",
  "What Ponos must do every time": "Ce que Ponos doit faire à chaque fois",
  "Copied into every ticket created.": "Recopié dans chaque ticket créé.",
  "The road every ticket takes. Empty, the runner deduces it.": "Le chemin que prend chaque ticket. Vide, le runner le déduit.",
  "Run npm outdated in the repository, update what can be, and open a pull request. Done when the CI is green.":
    "Lancer npm outdated dans le dépôt, mettre à jour ce qui peut l'être et ouvrir une pull request. C'est fait quand la CI est verte.",
  "Turn on right away": "Activer tout de suite",
  "Turned on": "Activée",
  "Create the schedule": "Créer la récurrence",

  /* -- the Markdown editor ---------------------------------------------------- */
  /* The menu `/` opens and the bar over a selection. `Context` and `Link` are
     already said above. */
  "Paste a link…": "Collez un lien…",
  Bold: "Gras",
  Italic: "Italique",
  Strikethrough: "Barré",
  "Inline code": "Code en ligne",
  Text: "Texte",
  "Heading 1": "Titre 1",
  "Heading 2": "Titre 2",
  "Heading 3": "Titre 3",
  Quote: "Citation",
  Divider: "Séparateur",
  List: "Liste",
  "Bullet list": "Liste à puces",
  "Numbered list": "Liste numérotée",
  "To-do list": "Liste de tâches",
  Advanced: "Avancé",
  Code: "Code",
  Table: "Tableau",

  /* -- the projects ----------------------------------------------------------- */
  /* `Projects`, `Project`, `Repository`, `Where it is` and `The brief` are
     already said above, where the board and the configuration say them. */
  "What the tickets are about.": "Ce dont parlent les tickets.",
  "A project says where the work happens and what conventions hold there. One with no repository is not a mistake: its tickets come back as a document.":
    "Un projet dit où se fait le travail et quelles conventions y règnent. Un projet sans dépôt n'est pas une erreur : ses tickets reviennent sous forme de document.",
  Cards: "Cartes",
  Repository: "Dépôt",
  "On this machine": "Sur cette machine",
  "Last ticket": "Dernier ticket",
  "Last ticket {{when}}": "Dernier ticket {{when}}",
  "Sort by": "Trier par",
  Direction: "Sens",
  Descending: "Décroissant",
  Ascending: "Croissant",
  "Last ticket created": "Dernier ticket créé",
  "Number of tickets": "Nombre de tickets",
  "Tickets running": "Tickets en cours",
  Tickets: "Tickets",
  "code work": "travail de code",
  "document work": "travail de rédaction",
  "{{count}} ticket": "{{count}} ticket",
  "{{count}} tickets": "{{count}} tickets",
  repository: "dépôt",
  "on this machine": "sur cette machine",
  "Not cloned on this machine yet": "Pas encore cloné sur cette machine",
  "No repository: this project is a document": "Aucun dépôt : ce projet produit des documents",
  "Copy the path": "Copier le chemin",
  "No ticket points at this project yet.": "Aucun ticket ne pointe encore vers ce projet.",
  "Ticket created.": "Ticket créé.",
  "Produces documents": "Produit des documents",
  "{{count}} ready": "{{count}} à lancer",
  "{{count}} running": "{{count}} en cours",
  "{{count}} in review": "{{count}} en revue",
  "from the configuration": "depuis la configuration",
  "path set in the configuration": "chemin fixé dans la configuration",
  "{{count}} of {{total}} projects have a repository": "{{count}} projets sur {{total}} ont un dépôt",
  "{{count}} of {{total}} projects has a repository": "{{count}} projet sur {{total}} a un dépôt",
  "~/workspace/that-repository": "~/workspace/ce-depot",
  "Reading the projects…": "Lecture des projets…",
  "No project yet — a ticket without one comes back as a document.":
    "Aucun projet pour l'instant — un ticket sans projet revient sous forme de document.",
  "Its tickets are worked in its repository, and come back as a pull request.":
    "Ses tickets sont traités dans son dépôt, et reviennent en pull request.",
  "Its public address, if it has one. Optional.": "Son adresse publique, s'il en a une. Facultatif.",
  "Optional, and written later just as well: from the project's page.":
    "Facultatif, et tout aussi bien écrit plus tard : depuis la page du projet.",
  "A name is all it takes.": "Un nom suffit.",
  "The project": "Le projet",
  "Where its code is": "Où est son code",
  "One of the two is enough. A writing project has neither: its tickets come back as a document.":
    "L'un des deux suffit. Un projet de rédaction n'a ni l'un ni l'autre : ses tickets reviennent sous forme de document.",
  "A project needs a name.": "Un projet a besoin d'un nom.",
  "Write it as owner/repo, or paste the clone URL.": "Écrivez-le sous la forme propriétaire/dépôt, ou collez l'URL du clone.",
  "Edit the project": "Modifier le projet",
  "Repositories are looked for in {{path}}, and cloned there when they are nowhere.":
    "Les dépôts sont cherchés dans {{path}}, et clonés là quand ils n'existent nulle part.",
  "This project could not be read.": "Ce projet n'a pas pu être lu.",
  "No project called “{{name}}”.": "Aucun projet ne s'appelle « {{name}} ».",
  "Nothing is written on this page, so its tickets are told about the workspace and nothing about the project.":
    "Rien n'est écrit sur cette page : ses tickets reçoivent le contexte de l'espace de travail et rien sur le projet.",
  "This project is a line in config.toml and has no page: the board has never heard of it, so there is nothing here to write a brief on.":
    "Ce projet est une ligne de config.toml et n'a pas de page : le tableau n'en a jamais entendu parler, il n'y a donc rien ici sur quoi écrire un brief.",
  "Change its path in the settings.": "Changez son chemin dans les réglages.",
  "Open the project's page": "Ouvrir la page du projet",
  "Open full size": "Ouvrir en grand",
  "Image attached to the ticket": "Image jointe au ticket",
  "File attached to the ticket": "Fichier joint au ticket",
  "its pictures and the brief as it reads.":
    "ses images et le brief tel qu'il se lit.",

  /* -- a project's pictures ------------------------------------------------ */
  "Change the image": "Changer l'image",
  "The cover and the icon of the project's page.":
    "La couverture et l'icône de la page du projet.",
  Cover: "Couverture",
  Icon: "Icône",
  "Drop an image here, or paste one.": "Déposez une image ici, ou collez-en une.",
  "Choose a file": "Choisir un fichier",
  "Remove the cover": "Retirer la couverture",
  "Remove the icon": "Retirer l'icône",
  "Or the address of an image": "Ou l'adresse d'une image",
  "Or an emoji": "Ou un emoji",
  "Another emoji": "Un autre emoji",
  "Sending…": "Envoi…",
  "Use this image": "Utiliser cette image",
  "That file is not an image.": "Ce fichier n'est pas une image.",
  "This image could not be read.": "Cette image n'a pas pu être lue.",
  "The cover is changed": "La couverture est changée",
  "The icon is changed": "L'icône est changée",
  "The image was not changed": "L'image n'a pas été changée",
  "Kept here, not yet on the board":
    "Gardée ici, pas encore sur le board",
  "It is sent again at the next reading of the board.":
    "Elle sera renvoyée à la prochaine lecture du tableau.",
  "Not on the board yet — kept here, and sent again at the next reading: {{why}}":
    "Pas encore sur le board — gardée ici, et renvoyée à la prochaine lecture : {{why}}",
  "Not on the board yet — sent again at the next reading.":
    "Pas encore sur le board — renvoyée à la prochaine lecture.",
  "Changed on both sides: the board's picture was newer, and it won.":
    "Changée des deux côtés : celle du board était la plus récente, elle l'emporte.",
  "Changed on both sides: this one was newer, and it won on the board too.":
    "Changée des deux côtés : celle-ci était la plus récente, elle l'emporte aussi sur le board.",
  "This project is a line in config.toml; it is changed in the settings.":
    "Ce projet est une ligne de config.toml ; il se modifie dans les réglages.",
  "What the board calls it. A ticket points at this page, not at this name.":
    "Le nom que lui donne le tableau. Un ticket pointe vers cette page, pas vers ce nom.",
  "owner/repo, or the clone URL.": "propriétaire/dépôt, ou l'URL du clone.",
  "Write the whole address, from https://.": "Écrivez l'adresse entière, depuis https://.",
  "Only needed where the repository cannot be found on its own. Worktrees are made beside it, never in it.":
    "Utile seulement quand le dépôt ne se trouve pas tout seul. Les worktrees sont créés à côté, jamais dedans.",
  "The audience, the voice, the conventions, the things never to do. Every ticket of this project is told it before it is told the ticket.":
    "Le public, le ton, les conventions, ce qu'il ne faut jamais faire. Chaque ticket de ce projet le reçoit avant de recevoir le ticket.",
  "Write it as you would brief somebody joining the project.":
    "Écrivez-le comme à quelqu'un qui arrive sur le projet.",

  /* -- the standing context --------------------------------------------------- */
  Context: "Contexte",
  "Global context": "Contexte global",
  "Sent to Ponos in every ticket, for all the projects":
    "Envoyé à Ponos dans chaque ticket, pour tous les projets",
  "See all": "Voir tout",
  Fold: "Replier",
  "Write the context": "Écrire le contexte",
  "Nothing is written yet, so the tickets are told nothing about who the work is for.":
    "Rien n'est écrit pour l'instant : les tickets ne savent rien de pour qui le travail est fait.",
  "The changes made to the global context are not saved.":
    "Les modifications du contexte global ne sont pas enregistrées.",
  "Inherits the global context ↑": "Hérite du contexte global ↑",
  "{{count}} characters in every prompt": "{{count}} caractères dans chaque prompt",
  Reread: "Relire",
  "Saving…": "Enregistrement…",
  "Reading the context…": "Lecture du contexte…",
  "This board has no context page, so there is nowhere to write.":
    "Ce tableau n'a pas de page de contexte : il n'y a nulle part où écrire.",
  "Who you are, what the team does, the stack, the conventions, the things never to do. Keep it to one screen.":
    "Qui vous êtes, ce que fait l'équipe, la stack, les conventions, ce qu'il ne faut jamais faire. Tenez-vous à un écran.",
  "saved to the board, and read again on the next run.":
    "enregistré sur le tableau, relu au prochain ticket.",
  "The context is saved": "Le contexte est enregistré",
  "Every ticket from here on is told this.": "Chaque ticket à partir de maintenant le reçoit.",
  "The context was not saved": "Le contexte n'a pas été enregistré",

  /* -- the statistics, at the top of the dashboard ------------------------- */
  Statistics: "Statistiques",
  "24 h": "24 h",
  "7 days": "7 jours",
  "30 days": "30 jours",
  All: "Tout",
  Custom: "Personnalisée",
  From: "Du",
  To: "Au",
  "Counting the tickets…": "Je compte les tickets…",
  "Export (CSV)": "Exporter (CSV)",
  Open: "Ouverts",
  Closed: "Fermés",
  Created: "Créés",
  Spent: "Dépensé",
  "on the evening of the last day": "au soir du dernier jour",
  "moved to done or validated in the period": "passés en terminé ou validé sur la période",
  "added to the board in the period": "ajoutés au tableau sur la période",
  "by the runner's sessions in the period": "par les sessions du runner sur la période",
  "No ticket on the board over this period.": "Aucun ticket sur le tableau pendant cette période.",
  Activity: "Activité",
  "Tickets created and closed per day, still open each evening, and the spending per day":
    "Tickets créés et fermés par jour, encore ouverts chaque soir, et dépenses par jour",
  "Spent per day": "Dépenses",
  "Created, by type and sub-type": "Créés, par type et sous-type",
  "See by project ({{count}})": "Voir par projet ({{count}})",
  Hide: "Masquer",
  Unclassified: "Non classé",
  "Regression rate": "Taux de régression",
  Regression: "Régression",
  "{{rate}} before": "{{rate}} avant",
  "Bugs over bugs, features and improvements created in the period; the arrow compares it with the period of the same length before.":
    "Bugs sur bugs, fonctionnalités et améliorations créés sur la période ; la flèche le compare à la période de même durée juste avant.",
  "Created, by project": "Créés, par projet",
  "No project": "Sans projet",
  "{{open}} open · {{closed}} closed · {{created}} created · {{cost}} spent":
    "{{open}} ouverts · {{closed}} fermés · {{created}} créés · {{cost}} dépensés",
  "No ticket of this project over this period.": "Aucun ticket de ce projet pendant cette période.",
  "Created, by status": "Créés, par statut",
  "{{cost}} per closed ticket": "{{cost}} par ticket terminé",
  "Spent by the runner's sessions in the period; the average is over the tickets closed in it, all their sessions counted.":
    "Dépensé par les sessions du runner sur la période ; la moyenne porte sur les tickets terminés sur la période, toutes leurs sessions comprises.",
  "No ticket created in the period.": "Aucun ticket créé sur la période.",
  "No {{kind}} ticket created in the period.": "Aucun ticket {{kind}} créé sur la période.",
  "No ticket without a type created in the period.": "Aucun ticket sans type créé sur la période.",
  "A closing is dated by the runner's history when the runner closed the ticket ({{history}}), by the page's last edit otherwise ({{edited}}).":
    "Une fermeture est datée par l'historique du runner quand c'est lui qui a fermé le ticket ({{history}}), sinon par la dernière modification de la page ({{edited}}).",

  /* -- the settings page, in its own words ----------------------------------- */
  "Reading the configuration…": "Lecture de la configuration…",
  "could not read the configuration: {{why}}": "impossible de lire la configuration : {{why}}",
  yes: "oui",
  no: "non",
  "Written to the file": "Écrit dans le fichier",
  "No changes": "Aucune modification",
  "Unsaved changes": "Modifications non enregistrées",
  State: "État",

  /* -- the `name = value` table, a resource of its own ----------------------
     Its section blurb is already said where `web/settings.py` describes the
     file; only what the rows add is here. */
  "Where it is": "Où il se trouve",
  Accounts: "Comptes",
  Owner: "Propriétaire",
  Account: "Compte",
  "As GitHub spells it in the URL of a repository, before the slash.":
    "Tel que GitHub l'écrit dans l'URL d'un dépôt, avant la barre oblique.",
  "The account gh auth status names — logged in once with gh auth login.":
    "Le compte que nomme gh auth status — connecté une fois avec gh auth login.",
  "A row with no owner names nobody.": "Une ligne sans propriétaire ne nomme personne.",
  "An owner mapped to nothing is a row to remove.":
    "Un propriétaire qui ne mène nulle part est une ligne à retirer.",
  "One GitHub here — everything goes out as whoever gh is signed in as.":
    "Un seul GitHub ici — tout part sous le compte auquel gh est connecté.",
  "add an account": "Ajouter un compte",
  "Remove this account": "Retirer ce compte",
  Save: "Enregistrer",
  Diagnose: "Diagnostiquer",
  "Diagnose a problem": "Diagnostiquer un problème",
  "Diagnose a problem of {{project}}": "Diagnostiquer un problème de {{project}}",
  "Something does not work: a session finds why, then writes the tickets that fix it":
    "Quelque chose ne marche pas : une session trouve pourquoi, puis écrit les tickets qui le corrigent",

  /* -- the settings page, as `web/settings.py` describes the file ------------- */
  // The server sends one entry per key of `config.toml` — a title, a sentence
  // of help, what has to happen for a change to count, the words a choice is
  // shown in — and they arrive in the words that file is written in. Held to it
  // by the test suite. Those only the settings pages draw are in
  // `settings-french.ts`, fetched with them; here are the pages' titles, which
  // the menu of tabs draws, and the words the console also says elsewhere.

  // The six pages, the folded block, and the units a number is counted in.
  General: "Général",
  "The runner itself: its languages, its updates, this console, and the room it takes.":
    "Le runner lui-même : ses langues, ses mises à jour, cette console, et la place qu'il prend.",
  "Ticket source": "Source des tickets",
  Execution: "Exécution",
  "How tickets are picked up, what a session may do, and when your review is skipped.":
    "Comment les tickets sont pris, ce qu'une session peut faire, et quand votre relecture est sautée.",
  "Models and costs": "Modèles et coûts",
  "Who answers the sessions, which model works each ticket, and how much may be spent.":
    "Qui répond aux sessions, quel modèle traite chaque ticket, et combien peut être dépensé.",
  "Code and repositories": "Code et dépôts",
  Communication: "Communication",
  "How the runner reaches you, what a ticket shows while it runs, and its answers in comments.":
    "Comment le runner vous joint, ce qu'un ticket montre pendant qu'il tourne, et ses réponses en commentaire.",
  days: "jours",

  // The cards, and the sentence each opens on.
  Slack: "Slack",


  "Board storage": "Stockage du tableau",

  "Running tickets": "Exécution des tickets",
  "Check the board every (seconds)": "Consulter le tableau toutes les (secondes)",
  "Time limit per ticket (minutes)": "Durée maximale par ticket (minutes)",
  "Memory to keep free (MB)": "Mémoire à garder libre (Mo)",
  "Disk space to keep free (MB)": "Place disque à garder libre (Mo)",
  "Drop forgotten working copies after (days)": "Supprimer les copies de travail oubliées après (jours)",
  "Wait before resuming a killed session (seconds)": "Attente avant de reprendre une session tuée (secondes)",
  English: "Anglais",
  "Keep session logs (days)": "Garder les journaux de session (jours)",
  "Disk space: {{total}}": "Place sur le disque : {{total}}",

  "Models and usage": "Modèles et consommation",
  "Which Claude model works the tickets, and how much of your subscription the runner may spend.":
    "Quel modèle Claude traite les tickets, et quelle part de votre abonnement le runner peut consommer.",
  "Default model": "Modèle par défaut",
  // The sub-type's own word in these phrases, and its column head in the
  // table (« Feature »), stay in English: sub-types are not translated, see
  // SUBTYPES in subtypes.py.
  "Share kept for your own use (%)": "Part gardée pour votre usage (%)",

  "Repositories and pull requests": "Dépôts et pull requests",
  "What a Code ticket turns into: a branch, a pull request, and the merge once you validate it.":
    "Ce que devient un ticket Code : une branche, une pull request, et la fusion une fois que vous l'avez validé.",
  "Docker is installed, but its daemon does not answer: start it to turn this on.":
    "Docker est installé, mais son démon ne répond pas : démarrez-le pour activer ceci.",
  "Docker is not installed on this machine: this cannot be turned on without it.":
    "Docker n'est pas installé sur cette machine : ceci ne peut pas être activé sans lui.",
  "Wait for CI before merging (minutes)": "Attendre la CI avant de fusionner (minutes)",

  "Skip your review for some types of ticket. Once the session succeeds, the runner does what moving the ticket to Validated would do, then moves it to Done, and its report says so. A failed, blocked or out-of-credit ticket is never validated. All off: every ticket waits for you.":
    "Se passer de votre relecture pour certains types de ticket. Dès que la session réussit, le runner fait ce que ferait le passage en Validé, puis passe le ticket en Terminé, et son compte rendu le dit. Un ticket en échec, bloqué ou à court de crédits n'est jamais validé. Tout désactivé : chaque ticket vous attend.",

  "Ticket types": "Types de ticket",
  "A ticket's type decides how it is worked: Code (a repository and a pull request), Writing (the answer in the page), External action (in a browser or a service), Publication (prepared, then published once validated). An empty type is guessed before the ticket runs; a type you chose is never changed.":
    "Le type d'un ticket décide comment il est traité : Code (un dépôt et une pull request), Rédaction (la réponse dans la page), Action externe (dans un navigateur ou un service), Publication (préparée, puis publiée une fois validée). Un type vide est deviné avant que le ticket ne tourne ; un type que vous avez choisi n'est jamais changé.",
  "Every hour: only the minutes are read.": "Chaque heure : seules les minutes comptent.",
  "Model that finds ideas": "Modèle qui trouve les idées",

  Notifications: "Notifications",
  Monday: "Lundi",
  Tuesday: "Mardi",
  Wednesday: "Mercredi",
  Thursday: "Jeudi",
  Friday: "Vendredi",
  Saturday: "Samedi",
  Sunday: "Dimanche",
  "Desktop notification (older setting)": "Notification de bureau (ancien réglage)",
  "Kept for older files: “Notify on this computer's screen” follows it when it is not set itself.":
    "Gardé pour les anciens fichiers : « Notifier sur l'écran de cet ordinateur » le suit quand il n'est pas renseigné lui-même.",

  "Update progress every (seconds)": "Mettre à jour l'avancement toutes les (secondes)",

  "Look for new comments every (seconds)":
    "Chercher les nouveaux commentaires toutes les (secondes)",
  "Time limit per answer (minutes)": "Durée maximale par réponse (minutes)",
  "A prompt Ponos runs at every change of this ticket's status, with the old status, the new one and the ticket. Empty, nothing runs.":
    "Un prompt que Ponos exécute à chaque changement de statut de ce ticket, avec l'ancien statut, le nouveau et le ticket. Vide, rien ne s'exécute.",
  "If it goes to validated, create the deployment ticket.":
    "Si on passe en validé, crée le ticket de déploiement.",
  "Save the prompt": "Enregistrer le prompt",
  Automation: "Automatisation",
  "Automation (On)": "Automatisation (On)",
  "No prompt on this ticket.": "Aucun prompt sur ce ticket.",
  "has an automation prompt": "a un prompt d'automatisation",
  "When this ticket goes to done, create a ticket that applies the recommendations of the Result.":
    "Quand ce ticket passe à done, crée un ticket qui applique les recommandations du Résultat.",
  "Optional. A prompt Ponos runs at every change of this ticket's status — for example, to chain a follow-up ticket.":
    "Facultatif. Un prompt que Ponos exécute à chaque changement de statut de ce ticket — par exemple pour enchaîner un ticket de suite.",
  "Prompt saved": "Prompt enregistré",
  "Prompt removed": "Prompt retiré",
  "not started": "pas encore lancé",
  "being run": "en cours d'exécution",
  "ran": "exécuté",
  "stopped on an error": "arrêté sur une erreur",
  "not run": "non exécuté",
  generation: "génération",
  "Look for moved statuses every (seconds)": "Chercher les statuts modifiés toutes les (secondes)",
  "Time limit per prompt (minutes)": "Durée maximale par prompt (minutes)",
  "Look at a blocked ticket every (seconds)": "Réexaminer un ticket bloqué toutes les (secondes)",

  "Web console": "Console web",
  "Refresh the board every (seconds)": "Rafraîchir le tableau toutes les (secondes)",
  "Time limit per discussion reply (minutes)":
    "Durée maximale d'une réponse de la discussion (minutes)",
  "Largest attached file (MB)": "Taille maximale d'un fichier joint (Mo)",
  "Keep attached files (days)": "Garder les fichiers joints (jours)",

  "Look for an update every (seconds)": "Chercher une mise à jour toutes les (secondes)",

  "Pull request": "Pull request",
  Session: "Session",
  Progress: "Avancement",
  "Prompt on status change": "Prompt à chaque changement de statut",
  Type: "Type",
  "Sub-type": "Sous-type",
  Goal: "Objectif",

  // Said by the first connection too.
  "Slack bot token": "Jeton du bot Slack",
  "Slack channel ID": "Identifiant du canal Slack",
  "Anthropic API key": "Clé API Anthropic",
  "OpenRouter key": "Clé OpenRouter",

  // Said by the server elsewhere too — a check of the health band, a column,
  // a priority — on pages that do not fetch `settings-french.ts`.
  seconds: "secondes",
  minutes: "minutes",
  MB: "Mo",
  "%": "%",
  Worktrees: "Worktrees",
  French: "Français",
  Low: "Faible",
  High: "Élevée",
  Updates: "Mises à jour",
  Machine: "Machine",
  Duration: "Durée",
  "Waiting for credit": "En attente de crédit",
  Agent: "Agent",
  "Tickets database": "Base des tickets",
  "Projects database": "Base des projets",
  "GitHub access": "Accès à GitHub",
  Version: "Version",
  "Disk space": "Place sur le disque",
  "GitHub connected": "GitHub connecté",
  classic: "classique",
  "fine-grained": "à granularité fine",
  "Claude Code": "Claude Code",
  "Client": "Client",
  "Worktree setup": "Préparation du worktree",
  "Repository path": "Chemin du dépôt",
  "Where this project's repository is on this machine. Empty: the page's Path property, then the clone found under the workspace root by its GitHub address.":
    "Où se trouve le dépôt de ce projet sur cette machine. Vide : la propriété Path de la page, puis le clone trouvé sous la racine de l'espace de travail par son adresse GitHub.",
  "Path": "Chemin",
  "Vault keys": "Clés du coffre",
  "The environment variables this project's sessions are given, and the vault item each is read from. Never the values: only where to read them.":
    "Les variables d'environnement que reçoivent les sessions de ce projet, et l'élément du coffre où chacune est lue. Jamais les valeurs : seulement où les lire.",
  "Keys": "Clés",
  "One per line: `NPM_TOKEN = hermez/npm`, or `NPM_TOKEN` alone to read it under its own name.":
    "Une par ligne : `NPM_TOKEN = hermez/npm`, ou `NPM_TOKEN` seul pour la lire sous son propre nom.",
  "Plan first": "Plan d'abord",
  "The first session proposes a plan and waits for your yes before writing any code.":
    "La première session propose un plan et attend votre oui avant d'écrire du code.",
  "Before and after": "Avant et après",
  Before: "Avant",
  After: "Après",
  "Before and after captures": "Captures avant et après",
  "After the commits of a code ticket, the project is started on the base and on the branch and each page is photographed; the pictures join the pull request and the ticket. Nothing starts while the command is empty.":
    "Après les commits d'un ticket de code, le projet est lancé sur la base et sur la branche et chaque page est photographiée ; les images rejoignent la pull request et le ticket. Rien ne se lance tant que la commande est vide.",
  "No Chrome is installed here: nothing can be photographed.": "Aucun Chrome n'est installé ici : rien ne peut être photographié.",
  "Preview command": "Commande de prévisualisation",
  "Preview address": "Adresse de prévisualisation",
  Pages: "Pages",
  "Active.": "Actif.",
  "Off: set a command and an address.": "Désactivé : renseigne une commande et une adresse.",
  "Claude provider": "Fournisseur Claude",
  "Language": "Langue",
  "Claude Code is not signed in.": "Claude Code n'est pas connecté.",

  // Not said by the settings page any more, but still said elsewhere: the menu
  // and the projects' own list, and the ticket types a board's default columns
  // are written in.
  Projects: "Projets",
  Writing: "Rédaction",
  "External action": "Action externe",
  Publication: "Publication",
  // The first connection, in steps — components/console/setup.tsx, components/console/setup/ and lib/setup.ts.
  "First connection": "Première connexion",
  "no status": "sans statut",
  "Access": "Accès",
  "Continue": "Continuer",
  "Checking…": "Vérification…",
  "No board yet.": "Pas encore de tableau.",
  "Link of the page you shared": "Lien de la page partagée",
  "Only to build a second board: the one above stays where it is otherwise.":
    "Seulement pour construire un second tableau : sinon celui ci-dessus reste où il est.",
  "Left empty, only the token is written — `ponos init <page>` builds the board later.":
    "Laissé vide, seul le jeton est écrit — `ponos init <page>` construira le tableau plus tard.",
  "Connect and build the board": "Connecter et construire le tableau",
  "Check again": "Vérifier à nouveau",
  "Claude Code is not installed on this machine": "Claude Code n'est pas installé sur cette machine",
  "Claude Code is not signed in": "Claude Code n'est pas connecté",
  // The settings' GitHub page.
  "The GitHub App tickets clone, push and open their pull requests with.":
    "La GitHub App avec laquelle les tickets clonent, poussent et ouvrent leurs pull requests.",
  // The access token, on the GitHub page and in the setup.
  // Settings › Code › GitHub access.
  "What this console runs on": "Ce sur quoi tourne cette console",
  "Error": "Erreur",
  "Board": "Tableau",
  "Find me ideas": "Trouve-moi des idées",
  "Ponos, find me ideas": "Ponos, trouve-moi des idées",
  "Ideas": "Idées",
  "Ideas for {{name}}": "Idées pour {{name}}",
  "Swipe right to keep an idea, left to throw it away.":
    "Glisse à droite pour garder une idée, à gauche pour la jeter.",
  "← throw away · → keep · Ctrl/Cmd+Z undo": "← jeter · → garder · Ctrl/Cmd+Z annuler",
  "Swipe right to keep, left to throw away.": "Glisse à droite pour garder, à gauche pour jeter.",
  "Swipe": "Idées",
  "Kept": "Gardée",
  "Thrown": "Jetée",
  "Keep": "Garder",
  "Throw away": "Jeter",
  "Undo": "Annuler",
  "Ponos is looking for ideas…": "Ponos cherche des idées…",
  "No ideas could be found.": "Aucune idée n'a pu être trouvée.",
  "No more ideas": "Plus d'idées",
  "Ten more": "Encore 10",
  "New project": "Nouveau projet",
  "Workspace": "Espace de travail",
  "What Ponos proposed, kept or thrown away, for the workspace and for each project.":
    "Ce que Ponos a proposé, gardé ou jeté, pour l'espace de travail et pour chaque projet.",
  "All projects": "Tous les projets",
  "Project created: {{title}}": "Projet créé : {{title}}",
  "Ticket created: {{title}}": "Ticket créé : {{title}}",
  "Open the project": "Ouvrir le projet",
  "Open the ticket": "Ouvrir le ticket",
  "The decision could not be saved": "La décision n'a pas pu être enregistrée",
  "Run now": "Lancer maintenant",
  "Delete the schedule": "Supprimer la récurrence",
  "The schedule could not be deleted": "La récurrence n'a pas pu être supprimée",
  "Schedule “{{name}}” deleted": "Récurrence « {{name}} » supprimée",
  "Ponos will stop creating this ticket. The tickets it already made stay where they are.":
    "Ponos cessera de créer ce ticket. Les tickets déjà créés restent en place.",
  "The schedule could not be run": "La récurrence n'a pas pu être lancée",
  "Project “{{name}}” deleted": "Projet « {{name}} » supprimé",
  "Its page was put aside in the board's trash folder.":
    "Sa page a été mise de côté dans le dossier trash du tableau.",
  "Delete “{{name}}”?": "Supprimer « {{name}} » ?",
  "Ponos will stop following this project.": "Ponos va cesser de suivre ce projet.",
  "Ponos will stop following this project. No ticket points at it.":
    "Ponos va cesser de suivre ce projet. Aucun ticket n'y est lié.",
  "Ponos will stop following this project. {{count}} ticket points at it.":
    "Ponos va cesser de suivre ce projet. {{count}} ticket y est lié.",
  "Ponos will stop following this project. {{count}} tickets point at it.":
    "Ponos va cesser de suivre ce projet. {{count}} tickets y sont liés.",
  "It disappears from the console and is no longer synchronised: the runner takes none of its tickets, and no more tokens are spent on it.":
    "Il disparaît de la console et n'est plus synchronisé : le runner ne prend aucun de ses tickets et plus aucun token n'est dépensé pour lui.",
  "Its page goes to the board's trash, where it is kept and can be restored.":
    "Sa page part à la corbeille du board, où elle est gardée et reste récupérable.",
  "Its tickets are deleted too.":
    "Ses tickets sont supprimés aussi.",
  "Its tickets stay on the board; those that are ready or in progress are blocked, with a comment saying why.":
    "Ses tickets restent sur le tableau ; ceux qui sont prêts ou en cours passent en bloqué, avec un commentaire qui explique pourquoi.",
  "The GitHub repository and the folder on this machine are never deleted. Its throwaway worktrees are cleaned up.":
    "Le dépôt GitHub et le dossier sur cette machine ne sont jamais supprimés. Ses worktrees jetables sont nettoyées.",
  "Its ideas are deleted; what it cost stays in the statistics.":
    "Ses idées sont supprimées ; ce qu'il a coûté reste dans les statistiques.",
  "Also delete its {{count}} ticket":
    "Supprimer aussi son ticket",
  "Also delete its {{count}} tickets":
    "Supprimer aussi ses {{count}} tickets",
  "Yes, I am sure I want to delete this project": "Oui, je suis sûr de supprimer ce projet",
  "Deleting…": "Suppression…",
  "Delete the project": "Supprimer le projet",
  "More actions on “{{name}}”": "Autres actions sur « {{name}} »",
  "All ideas": "Toutes les idées",
  "New idea": "Nouvelle idée",
  "New": "Nouvelle",
  "Turned into a ticket": "Transformée en ticket",
  "New ideas": "Nouvelles",
  "Kept ideas": "Gardées",
  "Thrown ideas": "Jetées",
  "Became tickets": "En tickets",
  "Back to new": "Remettre en nouvelle",
  "Idea kept: {{title}}": "Idée gardée : {{title}}",
  "Idea thrown away: {{title}}": "Idée jetée : {{title}}",
  "Idea back to new: {{title}}": "Idée remise en nouvelle : {{title}}",
  "Turn into a ticket": "Transformer en ticket",
  "Written by": "Écrite par",
  "Written by anyone": "Tous les auteurs",
  "Written by Ponos": "Écrites par Ponos",
  "Written by us": "Écrites par nous",
  "Edited by {{name}}": "Modifiée par {{name}}",
  "Idea saved: {{title}}": "Idée enregistrée : {{title}}",
  "No idea yet.": "Aucune idée pour l'instant.",
  "No new idea.": "Aucune nouvelle idée.",
  "Show all": "Tout afficher",
  "Every idea is sorted: kept, thrown away or turned into a ticket.": "Toutes les idées sont triées : gardées, jetées ou passées en ticket.",
  "No idea matches these filters.": "Aucune idée ne correspond à ces filtres.",
  "Another status, category, score, author or project, and they will be back.":
    "Un autre statut, catégorie, score, auteur ou projet, et elles reviendront.",
  Category: "Catégorie",
  "All categories": "Toutes les catégories",
  "Score": "Score",
  "All scores": "Tous les scores",
  "Green (70 and up)": "Vert (70 et plus)",
  "Orange (40 to 69)": "Orange (de 40 à 69)",
  "Red (under 40)": "Rouge (moins de 40)",
  "Not scored": "Non noté",
  "Not scored — try again": "Non noté — réessayer",
  "Being scored…": "En cours de notation…",
  "Relevance {{score}} out of 100": "Pertinence {{score}} sur 100",
  "Order": "Ordre",
  "Most relevant first": "Par pertinence",
  "Newest first": "Les plus récentes d'abord",
  "Score the unscored ideas ({{count}})": "Noter les idées non notées ({{count}})",
  "Scoring the ideas…": "Notation des idées…",
  "Score the unscored ideas?": "Noter les idées non notées ?",
  "{{ideas}} to score with {{model}} in {{calls}}: {{ceiling}} at most, each call stopped at its share.":
    "{{ideas}} à noter avec {{model}} en {{calls}} : {{ceiling}} au plus, chaque appel arrêté à sa part.",
  "{{count}} idea": "{{count}} idée",
  "{{count}} ideas": "{{count}} idées",
  "{{count}} call": "{{count}} appel",
  "{{count}} calls": "{{count}} appels",
  "the light model": "le modèle léger",
  "Score them": "Les noter",
  "The ideas could not be scored": "Les idées n'ont pas pu être notées",
  "Not sorted": "Non classée",
  // The categories themselves (UX/UI, Feature, Security, Tech) are not here:
  // they are the developers' words, untranslated — see CATEGORY_WORDS.
  "Tech is refactoring, performance and debt — not a new feature.":
    "Tech, c’est la refacto, la performance et la dette — pas une nouvelle fonctionnalité.",
  "Write one, or ask Ponos for a batch.": "Écrivez-en une, ou demandez une série à Ponos.",
  "Idea": "Idée",
  "For": "Pour",
  "Create the project": "Créer le projet",
  "Done when": "Terminée quand",
  "Out of scope": "Hors périmètre",
  "Where": "Où",
  "An idea needs a title": "Une idée a besoin d'un titre",
  "A title fits in 90 characters": "Un titre tient en 90 caractères",
  "This idea is no longer there.": "Cette idée n'existe plus.",
  "The idea, in one line.": "L'idée, en une ligne.",
  Description: "Description",
  "Why it is worth doing.": "Pourquoi elle vaut la peine.",
  "The idea, in one line": "L'idée, en une ligne",
  "Why it is worth it — context, link, example…": "Pourquoi elle vaut la peine — contexte, lien, exemple…",
  "Refactoring, performance, technical debt — not a new feature.":
    "Refacto, performance, dette technique — pas une nouvelle fonctionnalité.",
  "Project: {{name}}": "Projet : {{name}}",
  "Propose a new project": "Proposer un nouveau projet",
  "The idea becomes a project-creation ticket.": "L'idée devient un ticket de création de projet.",
  "Create another": "En créer une autre",
  "Ctrl + Enter": "Ctrl + Entrée",
  "⌘ + Enter": "⌘ + Entrée",
  "Create the idea": "Créer l'idée",
  Id: "Id",
  "Last modified": "Dernière modification",
  "Title or id": "Titre ou id",
  "any status": "tous les statuts",
  "any priority": "toutes les priorités",
  "any type": "tous les types",

  /* -- What waits for you, on a phone (to-handle.tsx) and the board's tabs -- */
  "To handle": "À traiter",
  "Nothing waits for you: no ticket is blocked or in review.":
    "Rien ne vous attend : aucun ticket bloqué ni en revue.",
  "Show the other one": "Voir l'autre",
  "Show the {{count}} others": "Voir les {{count}} autres",
  "Columns of the board": "Colonnes du board",

  /* -- Unblock and Decide (ticket-decision.tsx, lib/decision.ts) ----------- */
  Unblock: "Débloquer",
  Decide: "Décider",
  /* The series of a column's tickets, one after another (ticket-series.tsx). */
  "Unblock ({{count}})": "Débloquer ({{count}})",
  "Decide ({{count}})": "Décider ({{count}})",
  "Unblock the tickets": "Débloquer les tickets",
  "Decide on the tickets in review": "Décider des tickets en revue",
  "The blocked tickets, one after another": "Les tickets bloqués, l'un après l'autre",
  "The tickets in review, one after another": "Les tickets en revue, l'un après l'autre",
  "Ticket unblocked": "Ticket débloqué",
  "Ticket decided": "Ticket décidé",
  "Nothing left to unblock.": "Plus rien à débloquer.",
  "Nothing left to decide.": "Plus rien à décider.",
  "Ticket {{at}} of {{count}}": "Ticket {{at}} sur {{count}}",
  "This ticket left the series: it moved elsewhere.": "Ce ticket a quitté la série : il a bougé ailleurs.",
  "The ticket was not put back": "Le ticket n'a pas été remis en place",
  Skip: "Passer",
  Decided: "Décidé",
  "→ or J: skip · ← or K: previous · 1–9: a choice · Esc: close":
    "→ ou J : passer · ← ou K : précédent · 1–9 : un choix · Échap : fermer",
  "↵ or R: ready · A: abandon · → or J: skip · ← or K: previous · Esc: close":
    "↵ ou R : prêt · A : abandonner · → ou J : passer · ← ou K : précédent · Échap : fermer",
  "Sort the drafts": "Trier les brouillons",
  "Sort ({{count}})": "Trier ({{count}})",
  "The drafts, one after another": "Les brouillons, l'un après l'autre",
  "Draft sorted": "Brouillon trié",
  "No draft left to sort.": "Plus aucun brouillon à trier.",
  "{{count}} draft sorted": "{{count}} brouillon trié",
  "{{count}} drafts sorted": "{{count}} brouillons triés",
  "{{count}} ticket unblocked": "{{count}} débloqué",
  "{{count}} tickets unblocked": "{{count}} débloqués",
  "{{count}} ticket decided": "{{count}} décidé",
  "{{count}} tickets decided": "{{count}} décidés",
  "{{count}} ticket skipped": "{{count}} passé",
  "{{count}} tickets skipped": "{{count}} passés",
  "Review the skipped tickets": "Revoir les tickets passés",
  "A decision to make": "Une décision à prendre",
  "Missing access": "Accès manquant",
  "Something to do by hand": "Action manuelle requise",
  "Out of credit": "Crédits épuisés",
  "Failing checks": "CI en échec",
  Conflict: "Conflit",
  "Too big for one ticket": "Trop gros pour un ticket",
  Stuck: "Bloqué",
  "Yes, go ahead": "Oui, vas-y",
  "Answer the question": "Répondre à la question",
  "It's done, run it again": "C'est fait, relancer",
  "Run it again on another model": "Relancer avec un autre modèle",
  "Run it again with an instruction": "Relancer en ajoutant une consigne",
  "Split into sub-tickets": "Découper en sous-tickets",
  "Abandon — move to done": "Abandonner — passer en terminé",
  "Abandon — move to cancelled": "Abandonner — passer en abandonné",
  "your decision is awaited": "votre décision est attendue",
  "Your decision is awaited": "Votre décision est attendue",
  "Other: write an instruction": "Autre : écrire une consigne",
  "Send back with an instruction": "Renvoyer en cours avec une consigne",
  "Fix the CI": "Corriger la CI",
  "Add the missing tests": "Ajouter les tests manquants",
  "Take the screenshots": "Faire les captures demandées",
  "Rebase onto the base branch": "Rebaser sur la branche de base",
  "Send back on this point": "Renvoyer sur ce point",
  Reject: "Rejeter",
  "The instruction the next session reads": "La consigne que lira la prochaine session",
  "A note, if you want one": "Une note, si vous voulez",
  "The model it runs on next": "Le modèle de la prochaine session",
  "One sub-ticket a line": "Un sous-ticket par ligne",
  "Checks pass": "Checks au vert",
  "Checks fail": "Checks en échec",
  "Checks running": "Checks en cours",
  "No checks": "Pas de checks",
  "Checks unknown": "Checks inconnus",
  Checks: "Checks",
  Passed: "Réussi",
  "Files changed": "Fichiers modifiés",
  "This ticket could not be read: {{why}}": "Ce ticket n'a pas pu être lu : {{why}}",
  "The run did not say why.": "La session n'a pas dit pourquoi.",
  "Set aside by hand: no run said why.": "Mis de côté à la main : aucune session n'a dit pourquoi.",
  "What it delivered": "Ce qui a été livré",
  "The run said nothing more.": "La session n'en a pas dit plus.",
  CI: "CI",
  "Points to check": "Points d'attention",
  "The agent flagged nothing.": "L'agent n'a rien signalé.",
  "The decision was not sent": "La décision n'a pas été envoyée",
  "Your decision": "Votre décision",
  "Send and run again": "Envoyer et relancer",
  "Your answer": "Votre réponse",
  "Yes, close it": "Oui, clos-le",
  Yes: "Oui",
  No: "Non",
  "Run it again as it is": "Relancer tel quel",
  "Quick replies": "Réponses rapides",
  Abandon: "Abandonner",
  "Abandon this ticket?": "Abandonner ce ticket ?",
  "See the session": "Voir la session",
  "Answer Ponos or give it an instruction…": "Répondez à Ponos ou donnez-lui une consigne…",
  "Same model": "Même modèle",
  "Same model ({{model}})": "Même modèle ({{model}})",
  "Ponos is working…": "Ponos travaille…",
  Confirm: "Confirmer",
  "This machine": "Cette machine",
  "What an MCP is, how to plug Ponos into Claude, and the ones the sessions use.": "Ce qu'est un MCP, comment brancher Ponos à Claude, et ceux qu'utilisent les sessions.",
  "MCP": "MCP",
  "Triggers": "Déclencheurs",
  "The addresses a tool calls — Sentry, GitHub Actions, anything — to open a ticket.": "Les adresses qu'un outil appelle — Sentry, GitHub Actions, n'importe lequel — pour ouvrir un ticket.",
  // Conversations — the ones kept by the console, and the model they run on.
  Conversations: "Conversations",
  Chat: "Chat",
  "Every conversation with your workspace. Open one to carry on where it stopped.":
    "Toutes les conversations avec votre espace de travail. Ouvrez-en une pour reprendre là où elle s'était arrêtée.",
  "New conversation": "Nouvelle conversation",
  "Search the titles and what was said": "Chercher dans les titres et dans ce qui s'est dit",
  "Reading the conversations…": "Lecture des conversations…",
  "No conversation matches.": "Aucune conversation ne correspond.",
  "Other words, and they will be back.": "D'autres mots, et elles reviendront.",
  "No conversation yet.": "Aucune conversation pour l'instant.",
  "Every conversation with your workspace is kept here, to be carried on later.":
    "Chaque conversation avec votre espace de travail est gardée ici, pour être reprise plus tard.",
  "Untitled conversation": "Conversation sans titre",
  open: "ouverte",
  "{{count}} exchange": "{{count}} échange",
  "{{count}} exchanges": "{{count}} échanges",
  "found in the conversation": "trouvé dans la conversation",
  Rename: "Renommer",
  "The conversation could not be opened": "La conversation n'a pas pu être ouverte",
  "Conversation “{{name}}” deleted": "Conversation « {{name}} » supprimée",
  "Its conversation and the files sent in it are deleted for good.":
    "Sa conversation et les fichiers qui y ont été envoyés sont supprimés pour de bon.",
  "Delete the conversation": "Supprimer la conversation",
  "Yes, I am sure I want to delete this conversation": "Oui, je suis sûr de supprimer cette conversation",
  "Model of this conversation": "Modèle de cette conversation",
  "Search a model…": "Chercher un modèle…",
  "Reading the models…": "Lecture des modèles…",
  "No such model": "Aucun modèle de ce nom",
  "Recently used": "Utilisés récemment",
  "On the board": "Déjà sur le tableau",
  "no tools": "sans outils",
  "Cannot use tools, which Claude Code needs to work":
    "Ne gère pas les outils, dont Claude Code a besoin pour travailler",
  "Dollars per million tokens, read / written": "Dollars par million de tokens, lus / écrits",
  "{{price}} per million tokens": "{{price}} par million de tokens",
  "This model cannot use tools, which Claude Code needs to work: the ticket will probably fail.":
    "Ce modèle ne gère pas les outils, dont Claude Code a besoin pour travailler : le ticket échouera probablement.",
  "Only the Claude models, until OpenRouter is configured.":
    "Seulement les modèles Claude, tant qu'OpenRouter n'est pas configuré.",
  "Set up OpenRouter": "Configurer OpenRouter",

  /* -- a new project ------------------------------------------------------- */
  "Project created": "Projet créé",
  Name: "Nom",
  "Project name": "Nom du projet",
  "What the project does, in one sentence": "Ce que fait le projet, en une phrase",
  "Without a repository, its tickets come back as a document.":
    "Sans dépôt, les tickets reviennent sous forme de document.",
  "Where the repository is": "Où est le dépôt",
  "Local folder": "Dossier local",
  Site: "Site",
  "Conventions, context, instructions — what every ticket of this project is told first.":
    "Conventions, contexte, consignes — ce que chaque ticket de ce projet lit en premier.",
  "A project is already called “{{name}}”.": "Un projet s'appelle déjà « {{name}} ».",
  "Open it": "L'ouvrir",
  "Already cloned on this machine, at {{path}}.": "Déjà cloné sur cette machine, dans {{path}}.",
  "Not cloned on this machine yet: it will be at the first ticket.":
    "Pas encore cloné sur cette machine : il le sera au premier ticket.",
  "A git repository, whose origin is {{origin}}.": "Un dépôt git, dont l'origin est {{origin}}.",
  "A git repository, with no origin remote.": "Un dépôt git, sans remote origin.",
  "Create a first ticket": "Créer un premier ticket",
  Split: "Colonnes",
  "local folder": "dossier local",
  /* -- the installation's health, over the dashboard (health.py) ----------- */
  "Installation status": "État de l'installation",
  "{{count}} thing to fix before tickets can run": "{{count}} point à corriger pour que les tickets partent",
  "{{count}} things to fix before tickets can run": "{{count}} points à corriger pour que les tickets partent",
  "{{count}} thing to fix: {{channels}} notifications do not arrive":
    "{{count}} point à corriger : les notifications {{channels}} n'arrivent pas",
  "{{count}} things to fix: {{channels}} notifications do not arrive":
    "{{count}} points à corriger : les notifications {{channels}} n'arrivent pas",
  "{{count}} warning": "{{count}} avertissement",
  "{{count}} warnings": "{{count}} avertissements",
  "Recheck": "Revérifier",
  "Details":
    "Détails",
  "Probable cause:": "Cause probable :",
  "Open the link": "Ouvrir le lien",
  "Configure automatically?": "Corriger automatiquement ?",
  "Configure": "Configurer",
  "Done.": "C'est fait.",
  "GitHub": "GitHub",
  "Runner": "Runner",
  "ffmpeg": "ffmpeg",
  "git": "git",
  // The goals: their page, and the goal on a ticket.
  Goals: "Objectifs",
  "no goal": "aucun objectif",
  "All statuses": "Tous les statuts",
  "This goal is no longer there.": "Cet objectif n'existe plus.",
  "What the tickets are for, and how many of them are done.": "Ce à quoi servent les tickets, et combien sont faits.",
  "{{done}} of {{count}} ticket done": "{{done}} sur {{count}} ticket fait",
  "{{done}} of {{count}} tickets done": "{{done}} sur {{count}} tickets faits",
  Due: "Échéance",
  "No goal matches these filters.": "Aucun objectif ne correspond à ces filtres.",
  "Another status or project, and they will be back.": "Un autre statut ou projet, et ils reviendront.",
  "No goal.": "Aucun objectif.",
  "No ticket serves this goal yet.": "Aucun ticket ne sert encore cet objectif.",
  "Write one, then point the tickets that serve it at it.":
    "Écrivez-en un, puis rattachez-y les tickets qui le servent.",
  "The goal this ticket serves": "L'objectif que sert ce ticket",
  "New goal": "Nouvel objectif",
  "Edit the goal": "Modifier l'objectif",
  "Edit the goal “{{name}}”": "Modifier l'objectif « {{name}} »",
  "Launch v1": "Lancer la v1",
  "A goal needs a name": "Un objectif a besoin d'un nom",
  "One line: what this goal means.": "Une ligne : ce que cet objectif veut dire.",
  "How we know it is met. Observable, not an intention.":
    "Comment on sait qu'il est atteint. Observable, pas une intention.",
  "No status": "Aucun statut",
  "Met when": "Atteint quand",
  "E.g.: Ponos is ready for others": "Ex. : Ponos est prêt pour d'autres",
  "E.g.: an outsider installs Ponos alone": "Ex. : Une personne extérieure installe Ponos seule",
  "Goal created": "Objectif créé",
  "The tickets that serve this goal; its progress is counted from them.":
    "Les tickets qui servent cet objectif ; son avancement se compte à partir d'eux.",
  "Delete the goal": "Supprimer l'objectif",
  "The goal could not be deleted": "L'objectif n'a pas pu être supprimé",
  "Goal “{{name}}” deleted": "Objectif « {{name}} » supprimé",
  Reached: "Atteint",
  "Given up": "Abandonné",
  "Goal “{{name}}” reached": "Objectif « {{name}} » atteint",
  "Goal “{{name}}” given up": "Objectif « {{name}} » abandonné",
  "Active goals": "Objectifs actifs",
  "No active goal.": "Aucun objectif actif.",
  "Every goal is reached or given up.": "Tous les objectifs sont atteints ou abandonnés.",
  "The goal could not be changed": "L'objectif n'a pas pu être changé",
  "Change the goal": "Changer d'objectif",
  "No goal": "Aucun objectif",
  /* -- ideas on a schedule -------------------------------------------------- */
  "How often":
    "À quelle fréquence",
  "Every 4 hours":
    "Toutes les 4 heures",
  "Every N hours":
    "Toutes les N heures",
  "A cron expression":
    "Une expression cron",
  "On which day":
    "Quel jour",
  "hours":
    "heures",
  "Cron expression":
    "Expression cron",
  "Which projects":
    "Quels projets",
  "Selected projects":
    "Projets sélectionnés",
  "At":
    "À",
  "09:00":
    "09:00",
  "0 9 * * 1-5":
    "0 9 * * 1-5",
  "Next pass: {{when}}":
    "Prochaine passe : {{when}}",
  "No automatic search: ideas are found when you ask.":
    "Pas de recherche automatique : les idées se cherchent à la demande.",
  "Last pass: {{when}} - {{ideas}}":
    "Dernière passe : {{when}} - {{ideas}}",
  "{{count}} idea found":
    "{{count}} idée trouvée",
  "{{count}} ideas found":
    "{{count}} idées trouvées",
  "{{count}} project skipped":
    "{{count}} projet sauté",
  "{{count}} projects skipped":
    "{{count}} projets sautés",
  "No pass yet.":
    "Aucune passe pour l'instant.",
  "Never, only when I ask":
    "Jamais, seulement quand je le demande",
  "Ideas settings saved.":
    "Réglages des idées enregistrés.",
  "Ideas settings":
    "Réglages des idées",
  "When Ponos looks for ideas on its own, for which projects, and how much it may do. The button still works whatever is set here.":
    "Quand Ponos cherche des idées de lui-même, pour quels projets, et jusqu'où il peut aller. Le bouton marche toujours, quoi qu'on règle ici.",
  "Frequency":
    "Fréquence",
  "Every (hours)":
    "Toutes les (heures)",
  "Minute, hour, day, month, weekday: 0 9 * * 1-5 is weekdays at nine.":
    "Minute, heure, jour, mois, jour de la semaine : 0 9 * * 1-5 veut dire les jours ouvrés à neuf heures.",
  "Hours are this machine's{{zone}}. The searches run while the console does.":
    "Les heures sont celles de cette machine{{zone}}. Les recherches tournent tant que la console tourne.",
  "All projects, the ones added later too":
    "Tous les projets, ceux ajoutés plus tard aussi",
  "No project yet.":
    "Aucun projet pour l'instant.",
  "A project's own page can still turn it off: it is unticked there.":
    "La page d'un projet peut encore le désactiver : il est alors décoché ici.",
  "Ideas for the workspace, the ones that belong to no project":
    "Idées pour l'espace de travail, celles qui ne relèvent d'aucun projet",
  "Limits":
    "Garde-fous",
  "Ideas per project":
    "Idées par projet",
  "Skip above":
    "Sauter au-delà de",
  "Budget per pass ($)":
    "Budget par passe ($)",
  "none":
    "aucun",
  "A project with that many new ideas nobody has sorted is skipped, and the journal says so (0: never). The budget is read between two projects; empty is no ceiling.":
    "Un projet qui a autant d'idées nouvelles non triées est sauté, et le journal le dit (0 : jamais). Le budget est lu entre deux projets ; vide, pas de plafond.",
  "Last pass: {{cost}}.":
    "Dernière passe : {{cost}}.",
  "Tell me on my channels when a pass finds new ideas":
    "Me prévenir sur mes canaux quand une passe trouve de nouvelles idées",
  "The CLI's own model":
    "Le modèle propre au CLI",
  "Ponos finds ideas":
    "Ponos cherche des idées",
  "Last pass: it has happened.":
    "Dernière passe : elle a eu lieu.",
  "Due: Ponos looks for ideas then.":
    "À venir : Ponos cherche des idées à ce moment.",
  "Change it in the Ideas page's Settings":
    "À modifier dans les Réglages de la page Idées",

  /* -- a schedule beside the list (schedule-panel.tsx) ---------------------- */
  "Pick a schedule": "Choisissez une récurrence",
  "Its tickets, what they cost, and every pass it made are shown here.":
    "Ses tickets, ce qu'ils ont coûté et chacune de ses exécutions s'affichent ici.",
  Active: "Active",
  Paused: "En pause",
  "made by this schedule": "créés par cette récurrence",
  "no session has cost anything yet": "aucune session n'a encore rien coûté",
  "{{cost}} per run on average": "{{cost}} par exécution en moyenne",
  "The Cost of every ticket it made, added up; the average is over the tickets that have one.":
    "Le coût de chaque ticket créé, additionné ; la moyenne porte sur les tickets qui en ont un.",
  "per ticket, all its sessions counted": "par ticket, toutes ses sessions comprises",
  Success: "Réussite",
  "done, of the tickets that finished": "terminés, parmi les tickets arrivés au bout",
  "Done over done, failed and cancelled: a ticket still open has not said yet how it ends.":
    "Terminés sur terminés, échoués et abandonnés : un ticket encore ouvert n'a pas encore dit comment il finit.",
  "Last run": "Dernière exécution",
  "never yet": "jamais encore",
  "Next run": "Prochaine exécution",
  "Tickets and cost, by week": "Tickets et coût, par semaine",
  "Still open": "Encore ouverts",
  "Spent per week": "Dépensé par semaine",
  "Tickets made each week, how many of them are done or still open, and what they cost":
    "Les tickets créés chaque semaine, combien sont terminés ou encore ouverts, et ce qu'ils ont coûté",
  "Week of {{day}}": "Semaine du {{day}}",
  Runs: "Exécutions",
  "No ticket yet": "Aucun ticket pour l'instant",
  "The first one is born at the next run, or now with “Run now”.":
    "Le premier naît à la prochaine exécution, ou tout de suite avec « Lancer maintenant ».",
  "Turn it on, or try it once with “Run now”.": "Activez-la, ou essayez-la une fois avec « Lancer maintenant ».",
  "{{count}} of them were recognised by their title and their date: they were made before Ponos kept the link.":
    "{{count}} d'entre eux ont été reconnus à leur titre et à leur date : ils ont été créés avant que Ponos garde le lien.",
  "{{count}} of them was recognised by its title and its date: it was made before Ponos kept the link.":
    "{{count}} d'entre eux a été reconnu à son titre et à sa date : il a été créé avant que Ponos garde le lien.",
  "Run by hand": "Lancée à la main",
  Skipped: "Sautée",
  "No run yet": "Aucune exécution pour l'instant",
  "Every pass that makes a ticket, or makes none, is written here.":
    "Chaque passage qui crée un ticket, ou n'en crée pas, s'inscrit ici.",
  "Passes that made no ticket are kept since {{date}}.":
    "Les passages sans ticket sont gardés depuis le {{date}}.",
  "Passes that made no ticket are kept from this version on: the ones before were never recorded.":
    "Les passages sans ticket sont gardés à partir de cette version : ceux d'avant n'ont jamais été enregistrés.",
  "said from the ticket": "déduite du ticket",
  "The ticket of the previous run was still open.": "Le ticket de l'exécution précédente était encore ouvert.",

  /* -- what the server refuses with (lib/refusals.ts) ------------------------ */
  // The sentences the Python raises, translated on arrival; a test holds
  // `refusals.ts` to those `raise`s, and this list to `refusals.ts`.
  "The server answered {{status}}": "Le serveur a répondu {{status}}",
  "the board: {{error}}": "Le tableau : {{error}}",
  "the body is not JSON": "La requête n'est pas du JSON.",
  "invalid request": "Requête invalide.",
  "this request is too large for the console: send files as attachments, not inside the message":
    "Ce message est trop gros pour la console : joins les fichiers comme pièces jointes au lieu de les coller dans le texte, ou raccourcis-le.",
  "a goal needs a name": "Un objectif a besoin d'un nom.",
  "this workspace has no goals database": "Cet espace de travail n'a pas de base d'objectifs.",
  "nothing to change": "Rien à modifier.",
  "this board has no “{{column}}” column to point a ticket at a goal":
    "Ce tableau n'a pas de colonne « {{column}} » pour rattacher un ticket à un objectif.",
  "no goal with id {{id}}": "Aucun objectif ne porte l'identifiant {{id}}.",
  "this workspace has no schedules database": "Cet espace de travail n'a pas de base de récurrences.",
  "a schedule needs a name": "Une récurrence a besoin d'un nom.",
  "no schedule with id {{id}}": "Aucune récurrence ne porte l'identifiant {{id}}.",
  "unknown type “{{kind}}”": "Type inconnu : « {{kind}} ».",
  "unknown sub-type “{{subtype}}”": "Sous-type inconnu : « {{subtype}} ».",
  "this schedule is already being launched": "Cette récurrence est déjà en train d'être lancée.",
  "no ticket with id {{id}}":
    "Ce ticket n'existe pas : il a été supprimé, ou n'a jamais été sur ce board.",
  "no project with id {{id}}": "Aucun projet ne porte l'identifiant {{id}}.",
  "this workspace has no projects database": "Cet espace de travail n'a pas de base de projets.",
  "this brief changed in the board since it was opened":
    "Ce brief a changé dans le tableau depuis son ouverture : rechargez-le avant d'enregistrer.",
  "this brief holds what Markdown cannot keep; saving it would lose it":
    "Ce brief contient ce que le Markdown ne sait pas garder : l'enregistrer le perdrait.",
  "a project has a cover and an icon, not a {{slot}}": "Un projet a une couverture et une icône, pas de « {{slot}} ».",
  "a fix is made only once it is confirmed": "Une correction ne se fait qu'une fois confirmée.",
  "a run is in progress — try again once it has finished":
    "Une passe est en cours — réessayez une fois qu'elle sera terminée.",
  "{{label}}: yes or no": "{{label}} : oui ou non",
  "{{label}}: a number": "{{label}} : un nombre",
  "{{label}}: “{{offered}}” is not a number": "{{label}} : « {{offered}} » n'est pas un nombre",
  "{{label}}: {{minimum}} at the least": "{{label}} : {{minimum}} au minimum",
  "{{label}}: {{maximum}} at the most": "{{label}} : {{maximum}} au maximum",
  "{{label}}: a list": "{{label}} : une liste",
  "{{label}}: no such moment “{{moment}}”": "{{label}} : le moment « {{moment}} » n'existe pas",
  "{{label}}: one of {{choices}}": "{{label}} : l'une de ces valeurs, {{choices}}",
  "{{table}}: a list of {name, value}": "{{table}} : une liste de {name, value}",
  "settings: a table of name → value": "Réglages : une table nom → valeur",
  "a {{table}} row set to {{value}} has no name": "Une ligne de {{table}} réglée sur {{value}} n'a pas de nom.",
  "“{{name}}” maps to nothing — fill it in, or remove the row":
    "« {{name}} » ne correspond à rien — remplissez-la, ou retirez la ligne.",
  "“{{name}}” is named twice": "« {{name}} » apparaît deux fois.",
  "no such setting: {{name}}": "Ce réglage n'existe pas : {{name}}",
  "no such session": "Cette conversation n'existe pas.",
  "a session needs a title": "Une conversation a besoin d'un titre.",
  "no such attachment: {{identifier}} — it was removed, or the conversation is over": "Ce fichier n'existe pas : {{identifier}} — il a été retiré, ou la conversation est terminée.",
  "no such attachment: {{identifier}}": "Ce fichier n'existe pas : {{identifier}}",
  "“{{model}}” is not a model name": "« {{model}} » n'est pas un nom de modèle.",
  "an OpenRouter model needs the OpenRouter key: add it in the settings": "Un modèle OpenRouter demande la clé OpenRouter : ajoutez-la dans les réglages.",
  "nothing to send": "Il n'y a rien à envoyer.",
  "claude not found in PATH": "Claude est introuvable dans le PATH.",
  "{{model}} runs on OpenRouter, which has no key: pick a Claude model, or add the key in the settings": "{{model}} passe par OpenRouter, qui n'a pas de clé : choisissez un modèle Claude, ou ajoutez la clé dans les réglages.",
  "this run is for another conversation — reload the page": "Cet envoi vise une autre conversation — rechargez la page.",
  "no such waiting message": "Ce message en attente n'existe plus.",
  "unbalanced quotes: {{error}}": "Guillemets mal fermés : {{error}}",
  "no command": "Aucune commande.",
  "unknown command “{{verb}}” — try one of: {{offered}}": "Commande inconnue « {{verb}} » — essayez l'une de celles-ci : {{offered}}",
  "a command is already running": "Une commande est déjà en cours.",
  "a run needs a message from the user": "Un envoi a besoin d'un message de l'utilisateur.",
  "Waiting for a free place: other conversations are answering.": "En attente d'une place : d'autres conversations répondent.",
  "Answering": "En train de répondre",
  "Waiting for a free place": "En attente d'une place",
  "Unread answer": "Réponse non lue",
  "The conversation was not started": "La conversation n'a pas pu être commencée",
  "Its turn in progress is stopped first.": "Sa réponse en cours est arrêtée d'abord.",
  "Page not found": "Page introuvable",
  "This console has no page at {{path}}. Its pages are these:":
    "Cette console n'a pas de page à l'adresse {{path}}. Ses pages sont celles-ci :",
  // The accounts of a shared console — see web/accounts.py.
  "Who the console is shared with, and what each of them may do.": "Avec qui la console est partagée, et ce que chacun peut y faire.",
  Vault: "Coffre-fort",
  Memory: "Mémoire",
  Library: "Bibliothèque",
  "Keep in the library": "Garder dans la bibliothèque",
  "Kept in the library": "Gardé dans la bibliothèque",
  "The file could not be kept": "Le fichier n'a pas pu être gardé",
  "Reference files kept for the sessions, for all the projects or some.":
    "Fichiers de référence gardés pour les sessions, pour tous les projets ou pour certains.",
  Skills: "Skills",
  "The Claude Code skills Ponos gives its sessions, for all of them or for some projects.":
    "Les skills Claude Code que Ponos donne à ses sessions, à toutes ou à certains projets.",
  "What Ponos remembers from one session to the next, for all the projects or one.":
    "Ce que Ponos retient d'une session à l'autre, pour tous les projets ou pour un seul.",
  "What every ticket is told, for all the projects.": "Ce que reçoit chaque ticket, pour tous les projets.",
  "Everything a session is given besides its ticket": "Tout ce qu'une session reçoit en plus de son ticket",
  "Pick a project to read its page here. What every ticket is told lives in the Context page.":
    "Choisis un projet pour lire sa page ici. Ce que reçoit chaque ticket se trouve dans la page Contexte.",
  "Open the Context page": "Ouvrir la page Contexte",
  "The logins, passwords and API keys the sessions are given, kept encrypted.": "Les logins, mots de passe et clés d'API que reçoivent les sessions, gardés chiffrés.",
  "validated it": "l'a validé",
  "rejected it": "l'a refusé",
  "ran it again": "l'a relancé",
  "abandoned it": "l'a abandonné",
  "answered it": "a répondu",
  "created it as a draft": "l'a créé en brouillon",
  "created it": "l'a créé",
  "moved it to {{column}}": "l'a passé en {{column}}",
  "wrote in its discussion": "a écrit dans sa discussion",
  "set its priority to {{priority}}": "a mis sa priorité à {{priority}}",
  "changed its « On » prompt": "a changé son prompt « On »",
  "removed its « On » prompt": "a retiré son prompt « On »",
  "tied it to a goal": "l'a rattaché à un objectif",
  "untied it from its goal": "l'a détaché de son objectif",
  "From the console": "Depuis la console",
  "The token": "Le jeton",
  "Download": "Télécharger",
  "the text": "le texte",
  "Copy the text": "Copier le texte",
  "the Markdown": "le Markdown",
  "Copy the Markdown": "Copier le Markdown",
  "Markdown (.md)": "Markdown (.md)",
  "PDF (.pdf)": "PDF (.pdf)",
  "Version {{n}}": "Version {{n}}",
  "Request a change": "Demander une modification",
  "An earlier version: {{source}}, {{at}}.": "Une version précédente : {{source}}, {{at}}.",
  "Back to the latest": "Revenir à la dernière",
  "This version is the result again": "Cette version est de nouveau le résultat",
  "Make it the result again": "En refaire le résultat",
  "Saved as a new version: the one before is kept.": "Enregistré comme une nouvelle version : la précédente est gardée.",
  "Result saved": "Résultat enregistré",
  "What should change": "Ce qui doit changer",
  "What should change — the tone, a paragraph, a finding to check again…": "Ce qui doit changer — le ton, un paragraphe, un constat à revérifier…",
  "The ticket goes back to work with this instruction; its next result is a new version, this one kept.": "Le ticket repart avec cette consigne ; son prochain résultat en sera une nouvelle version, celle-ci gardée.",
  "Change requested": "Modification demandée",
  "No result rendered: the session said what it did, in the Journal tab, but handed back no deliverable.": "Aucun résultat rendu : la session a dit ce qu'elle a fait, dans l'onglet Journal, sans rendre de livrable.",
  "Nothing yet: the result comes with the first session that ends.": "Rien encore : le résultat arrive avec la première session terminée.",
  "merged": "fusionnée",
  "validated, being merged": "validée, en cours de fusion",
  "open, waiting for your review": "ouverte, attend votre relecture",
  "closed": "fermée",
  "View the diff": "Voir le diff",
  "retouched by {{who}}": "retouchée par {{who}}",
  "retouched by hand": "retouchée à la main",
  "kept from before": "reprise d'avant",
  "by a session": "par une session",
  "Journal": "Journal",
  "retouched its result": "a retouché son résultat",
  "asked for a change to its result": "a demandé une modification de son résultat",
}
