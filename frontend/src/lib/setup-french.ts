/* The French of the first connection: its steps, and what they repeat from the
   machine (`said.ts`).

   Apart from `french.ts`, as `health-french.ts` is, and fetched with the steps
   when they are drawn in French — the page `data-setup` serves, and the cards
   of the settings that reuse them: a console is connected once, and the first
   load of a French page is held to a budget (tests/test_release.py). A sentence
   the console also says somewhere else stays in `french.ts`. Same rule as
   there: the English sentence is the key. */

export const SETUP_FRENCH: Record<string, string> = {
  "Back to the console": "Retour à la console",
  "First project": "Premier projet",
  "First ticket": "Premier ticket",
  "Which language": "Quelle langue",
  "The console's, and the one Ponos writes its reports in. Both can be changed later in the settings.": "Celle de la console, et celle dans laquelle Ponos écrit ses comptes rendus. Les deux se changent ensuite dans les réglages.",
  "Missing: {{names}}": "Manque : {{names}}",
  "git, Claude Code and room on the disk": "git, Claude Code et de la place sur le disque",
  "Three gestures in Notion, and Ponos does the rest: it builds the Tickets and Projects databases itself, with every column spelled the way it reads them — there is no template to duplicate.": "Trois gestes dans Notion, et Ponos fait le reste : il construit lui-même les bases Tickets et Projets, chaque colonne écrite comme il la lit — aucun modèle à dupliquer.",
  "A board is connected: {{count}} ticket on it.": "Un tableau est connecté : {{count}} ticket dessus.",
  "A board is connected: {{count}} tickets on it.": "Un tableau est connecté : {{count}} tickets dessus.",
  "1. Create the Ponos integration": "1. Créez l'intégration Ponos",
  "Open Notion's integrations page, and click “New integration”.": "Ouvrez la page des intégrations de Notion, et cliquez sur « Nouvelle intégration ».",
  "Name it “Ponos”, choose your workspace, type “Internal”, and save.": "Nommez-la « Ponos », choisissez votre espace de travail, le type « Interne », et enregistrez.",
  "Under Capabilities, tick “Read comments” and “Insert comments”, then copy the “Internal Integration Secret”.": "Dans Capacités, cochez « Lire les commentaires » et « Insérer des commentaires », puis copiez le « Secret d'intégration interne ».",
  "Open Notion's integrations": "Ouvrir les intégrations Notion",
  "Integration secret": "Secret d'intégration",
  "Already saved — paste another one only to replace it.": "Déjà enregistré — n'en collez un autre que pour le remplacer.",
  "Check the token": "Vérifier le jeton",
  "Notion refused this token: copy the “Internal Integration Secret” again, from Notion's integrations page.": "Notion a refusé ce jeton : copiez à nouveau le « Secret d'intégration interne », depuis la page des intégrations de Notion.",
  "Notion knows this token: it is the integration “{{name}}”.": "Notion connaît ce jeton : c'est l'intégration « {{name}} ».",
  "2. Add Ponos to your Notion page": "2. Ajoutez Ponos à votre page Notion",
  "In Notion, open the page the board should live under — or create an empty one, “Ponos” for instance.": "Dans Notion, ouvrez la page sous laquelle le tableau doit vivre — ou créez-en une vide, « Ponos » par exemple.",
  "Click `···` at the top right of the page, then “Connections”.": "Cliquez sur `···` en haut à droite de la page, puis sur « Connexions ».",
  "Search for “{{name}}”, pick it, and confirm.": "Cherchez « {{name}} », choisissez-la, et confirmez.",
  "Come back here: the page appears below on its own.": "Revenez ici : la page apparaît ci-dessous toute seule.",
  "Open Notion": "Ouvrir Notion",
  "3. Choose where the board goes": "3. Choisissez où va le tableau",
  "Waiting for a page shared with “{{name}}”…": "En attente d'une page partagée avec « {{name}} »…",
  "A Ponos board is already there.": "Un tableau Ponos est déjà là.",
  "Use this board": "Utiliser ce tableau",
  "Pages shared with the integration": "Pages partagées avec l'intégration",
  "(untitled page)": "(page sans titre)",
  "Build the board under this page": "Construire le tableau sous cette page",
  "Notion's page menu, Connections open": "Le menu d'une page Notion, Connexions ouvert",
  "Share": "Partager",
  "Copy link": "Copier le lien",
  "Connections": "Connexions",
  "Search for connections…": "Rechercher des connexions…",
  "`···` → Connections → {{name}}": "`···` → Connexions → {{name}}",
  "A first project": "Un premier projet",
  "A ticket belongs to a project: the repository a code ticket works in, or simply a theme for writing. Pick a repository this machine already has, name one on GitHub — it is cloned at the first ticket —, or start with a project without code.": "Un ticket appartient à un projet : le dépôt dans lequel travaille un ticket de code, ou simplement un thème pour écrire. Choisissez un dépôt que cette machine a déjà, nommez-en un sur GitHub — il est cloné au premier ticket —, ou commencez par un projet sans code.",
  "Looking for repositories…": "Recherche des dépôts…",
  "The project “{{name}}” is created.": "Le projet « {{name}} » est créé.",
  "Projects on the board: {{names}}": "Projets sur le tableau : {{names}}",
  "Repositories found in {{root}}": "Dépôts trouvés dans {{root}}",
  "Already a project": "Déjà un projet",
  "Make it a project": "En faire un projet",
  "No repository in `{{root}}` yet — the folder where Ponos keeps them.": "Aucun dépôt dans `{{root}}` pour l'instant — le dossier où Ponos les range.",
  "Or a new one": "Ou un nouveau",
  "GitHub repository (optional)": "Dépôt GitHub (facultatif)",
  "Left empty, the project has no code: its tickets are written answers and documents.": "Laissé vide, le projet n'a pas de code : ses tickets sont des réponses écrites et des documents.",
  "A first ticket, played now": "Un premier ticket, joué tout de suite",
  "The proof that everything holds: Ponos writes a short ticket on your board and runs it at once — Claude reads it, answers, and the answer lands on the ticket. It takes a minute or two.": "La preuve que tout tient : Ponos écrit un court ticket sur votre tableau et le lance aussitôt — Claude le lit, répond, et la réponse arrive sur le ticket. Cela prend une minute ou deux.",
  "Writing the ticket…": "Écriture du ticket…",
  "Create and play the demonstration ticket": "Créer et jouer le ticket de démonstration",
  "It works: the ticket ran, and its answer is on the ticket. Ponos is ready.": "Ça marche : le ticket a tourné, et sa réponse est sur le ticket. Ponos est prêt.",
  "The ticket stopped on a question — open it to read what it needs.": "Le ticket s'est arrêté sur une question — ouvrez-le pour lire ce qu'il lui faut.",
  "The ticket did not run. What it said is below; the summary and its full diagnosis say which part is missing.": "Le ticket n'a pas tourné. Ce qu'il a dit est ci-dessous ; le récapitulatif et son diagnostic complet disent ce qui manque.",
  "Claude is working on it…": "Claude y travaille…",
  "Waiting for the run to start…": "En attente du lancement…",
  "See what is missing": "Voir ce qui manque",
  "Something does not work?": "Ça ne marche pas ?",
  "Running the diagnosis…": "Diagnostic en cours…",
  "Run the full diagnosis": "Lancer le diagnostic complet",
  "Copy it for support": "Le copier pour le support",
  "The same as `ponos doctor` in a terminal: every check, and what to do about each one that fails.": "Le même que `ponos doctor` dans un terminal : chaque vérification, et quoi faire pour chacune qui échoue.",
  "The runner's journal": "Le journal du runner",
  "Read the journal": "Lire le journal",
  "Read it again": "Le relire",
  "The same as `ponos logs --service` in a terminal: its last lines, with the trace of every error.": "Le même que `ponos logs --service` dans un terminal : ses dernières lignes, avec la trace de chaque erreur.",
  "Nothing written yet.": "Rien d'écrit pour l'instant.",
  "Steps": "Étapes",
  "Channels": "Canaux",
  "Summary": "Récapitulatif",
  "Who opens this console": "Qui ouvre cette console",
  "Nobody has claimed this console yet. The email and the password typed here are what it asks for from now on — and what closes this page behind you.":
    "Personne n'a encore réclamé cette console. L'e-mail et le mot de passe saisis ici sont ce qu'elle demandera désormais — et ce qui referme cette page derrière vous.",
  "Claiming…": "Réclamation…",
  "Claim the console": "Réclamer la console",
  "Installation code": "Code d'installation",
  "Printed by the console when it started — in a container, its logs (`docker compose logs ponos`, or the Logs tab in Dokploy). It is asked because this page is reached from outside the machine.":
    "Affiché par la console à son démarrage — dans un conteneur, ses logs (`docker compose logs ponos`, ou l'onglet Logs de Dokploy). Il est demandé parce que cette page est ouverte depuis l'extérieur de la machine.",
  "This console is reached from outside its machine and was started without an installation code: restart it, and read the code in its logs.":
    "Cette console est ouverte depuis l'extérieur de sa machine et a démarré sans code d'installation : redémarrez-la, et lisez le code dans ses logs.",
  "Email": "E-mail",
  "Password": "Mot de passe",
  "8 characters at the least: behind this console sits a runner that runs code on its machine.":
    "8 caractères au moins : derrière cette console tourne un runner qui exécute du code sur sa machine.",
  "The same password again": "Le même mot de passe, encore",
  "Claude Code CLI": "Claude Code CLI",
  "Your Claude subscription, signed in with `claude auth login`.":
    "Votre abonnement Claude, connecté avec `claude auth login`.",
  "The only one that keeps Claude in Chrome and waits for credits when the window runs out.":
    "Le seul qui garde Claude in Chrome et attend les crédits quand la fenêtre est épuisée.",
  "In a container, the command is typed once in its terminal.":
    "Dans un conteneur, la commande se tape une fois dans son terminal.",
  "A key from console.anthropic.com, billed by the token.":
    "Une clé de console.anthropic.com, facturée au token.",
  "Nothing to sign in, nothing to wait for — and no Claude in Chrome.":
    "Rien à connecter, rien à attendre — et pas de Claude in Chrome.",
  "One key for every provider, billed by OpenRouter.":
    "Une clé pour tous les providers, facturée par OpenRouter.",
  "Models are then named as OpenRouter slugs (`anthropic/claude-sonnet-4.5`, `openai/gpt-5`).":
    "Les modèles se nomment alors en slugs OpenRouter (`anthropic/claude-sonnet-4.5`, `openai/gpt-5`).",
  "No Claude in Chrome, nothing to wait for.": "Pas de Claude in Chrome, rien à attendre.",
  "Written to the configuration: {{said}}": "Écrit dans la configuration : {{said}}",
  "Claude Code is signed in as {{who}}.": "Claude Code est connecté en tant que {{who}}.",
  "Who answers the sessions": "Qui répond aux sessions",
  "The choice that matters most: it decides who bills the work, which models a ticket can name, and whether a ticket can use the browser. It can be changed later in the settings.":
    "Le choix le plus important : il décide qui facture le travail, quels modèles un ticket peut nommer, et si un ticket peut se servir du navigateur. Il se change plus tard dans les réglages.",
  "Open a terminal in the container — Dokploy's Terminal tab on the service, or `docker compose exec ponos bash` — and sign in there. The sign-in is kept in the `~/.claude` volume.":
    "Ouvrez un terminal dans le conteneur — l'onglet Terminal du service dans Dokploy, ou `docker compose exec ponos bash` — et connectez-vous là. La connexion est gardée dans le volume `~/.claude`.",
  "In a terminal on this machine, sign Claude Code in:":
    "Dans un terminal de cette machine, connectez Claude Code :",
  "Use the CLI": "Utiliser le CLI",
  "Claude Code is not installed in the container. In its terminal — Dokploy's Terminal tab on the service, or `docker compose exec ponos bash` — install it, then sign it in:":
    "Claude Code n'est pas installé dans le conteneur. Dans son terminal — l'onglet Terminal du service sur Dokploy, ou `docker compose exec ponos bash` —, installez-le, puis connectez-le :",
  "Claude Code is not installed on this machine. In a terminal, install it, then sign it in:":
    "Claude Code n'est pas installé sur cette machine. Dans un terminal, installez-le, puis connectez-le :",
  "Rather not install the CLI? An API key needs nothing on this machine.":
    "Pas envie d'installer le CLI ? Une clé API ne demande rien sur cette machine.",
  "Use an Anthropic API key": "Utiliser une clé API Anthropic",
  "Left empty, the key already in the configuration — or in the container's environment — is the one checked.":
    "Laissé vide, c'est la clé déjà dans la configuration — ou dans l'environnement du conteneur — qui est vérifiée.",
  "Run the sessions on OpenRouter": "Faire tourner les sessions sur OpenRouter",
  "Off, the key is only handed to the sessions, and they keep running on the CLI's sign-in.":
    "Décoché, la clé est seulement transmise aux sessions, qui continuent de tourner sur la connexion du CLI.",
  "Check and save": "Vérifier et enregistrer",
  "The board": "Le tableau",
  "Ponos keeps your tickets itself. Connecting a Notion board is optional, and you can do it later in the settings.":
    "Ponos garde lui-même vos tickets. Connecter un tableau Notion est facultatif, et vous pourrez le faire plus tard dans les réglages.",
  "A folder to keep under git.": "Un dossier à garder sous git.",
  "The board, in Notion": "Le tableau, dans Notion",
  "Building the board…": "Construction du tableau…",
  "GitHub, for the pull requests": "GitHub, pour les pull requests",
  "A code ticket comes back as a pull request. Connect GitHub in one click: Ponos creates its own GitHub App and you choose the repositories it reaches. Or paste an access token. Without either, `gh` is used — signed in with `gh auth login`, or given a token in `GH_TOKEN`, the way a container usually is.":
    "Un ticket de code revient en pull request. Connectez GitHub en un clic : Ponos crée sa propre GitHub App et vous choisissez les dépôts qu'elle atteint. Ou collez un jeton d'accès. Sans l'un ni l'autre, `gh` est utilisé — connecté avec `gh auth login`, ou muni d'un jeton dans `GH_TOKEN`, comme l'est d'ordinaire un conteneur.",
  "Pull requests are opened as {{account}}, with the token in `GH_TOKEN`.":
    "Les pull requests sont ouvertes en tant que {{account}}, avec le jeton de `GH_TOKEN`.",
  "Pull requests are opened as {{account}}.":
    "Les pull requests sont ouvertes en tant que {{account}}.",
  "gh is not signed in.": "gh n'est pas connecté.",
  "gh is not installed": "gh n'est pas installé",
  "claude is not installed": "Claude Code n'est pas installé",
  "Claude Code is not installed": "Claude Code n'est pas installé",
  "no token yet": "pas encore de jeton",
  "not signed in": "pas connecté",
  "the sessions run on OpenRouter: name its slugs": "les sessions passent par OpenRouter : nommez ses modèles par leur slug",
  "There is no Notion token yet.": "Il n'y a pas encore de jeton Notion.",
  "The Notion token and the board are not set yet.": "Le jeton Notion et le tableau ne sont pas encore réglés.",
  "The Notion token is not set yet.": "Le jeton Notion n'est pas encore réglé.",
  "The Notion board is not chosen yet.": "Le tableau Notion n'est pas encore choisi.",
  "No Anthropic API key is set.": "Aucune clé API Anthropic n'est renseignée.",
  "No OpenRouter key is set.": "Aucune clé OpenRouter n'est renseignée.",
  "{{name}} is not installed": "{{name}} n'est pas installé",
  "{{mb}} MB free on the disk": "{{mb}} Mo libres sur le disque",
  "Free {{missing}} MB: a ticket starts above {{minimum}} MB.":
    "Libérez {{missing}} Mo : un ticket démarre au-dessus de {{minimum}} Mo.",
  "Set `GH_TOKEN` in the service's environment and redeploy — or sign in from its terminal:":
    "Renseignez `GH_TOKEN` dans l'environnement du service et redéployez — ou connectez-vous depuis son terminal :",
  "In a terminal on this machine:": "Dans un terminal de cette machine :",
  "Asking gh…": "Question à gh…",
  "Pull requests are opened as {{account}}, through the GitHub App.":
    "Les pull requests sont ouvertes en tant que {{account}}, par la GitHub App.",
  "Or use an access token instead": "Ou utiliser plutôt un jeton d'accès",
  "Pull requests are opened as {{account}}, with the access token.":
    "Les pull requests sont ouvertes en tant que {{account}}, avec le jeton d'accès.",
  "{{account}} (token)": "{{account}} (jeton)",
  "Or, without the app:": "Ou, sans l'app :",
  "Being told, and answering": "Être prévenu, et répondre",
  "Optional — but on a server, the only way to hear about a blocked ticket: no desktop notification reaches you from a container. A question asked there is answered in the chat, and the answer lands on the ticket.":
    "Facultatif — mais sur un serveur, le seul moyen d'apprendre qu'un ticket est bloqué : aucune notification de bureau ne vous atteint depuis un conteneur. Une question posée là se répond dans la discussion, et la réponse arrive sur le ticket.",
  "Optional. A blocked ticket asks its question there, and what you answer lands on the ticket.":
    "Facultatif. Un ticket bloqué y pose sa question, et ce que vous répondez arrive sur le ticket.",
  "Bot token": "Jeton du bot",
  "@BotFather → `/newbot`, then say anything to your new bot: the chat id is read back from it.":
    "@BotFather → `/newbot`, puis écrivez n'importe quoi à votre nouveau bot : l'identifiant de discussion est relu depuis lui.",
  "Chat id": "Identifiant de discussion",
  "Found on its own — leave it empty unless you know it.":
    "Trouvé tout seul — laissez-le vide sauf si vous le connaissez.",
  "Then `/invite @your-bot` in the channel — the step everyone forgets.":
    "Puis `/invite @votre-bot` dans le canal — l'étape que tout le monde oublie.",
  "Save and check": "Enregistrer et vérifier",
  "One line per thing that has to work. A line that is missing can be fixed from its step now, or later from the settings — this summary is at the top of them.":
    "Une ligne par chose qui doit fonctionner. Une ligne manquante se corrige depuis son étape maintenant, ou plus tard depuis les réglages — ce récapitulatif est en haut de ceux-ci.",
  "Open the console": "Ouvrir la console",
  "OK": "OK",
  "Missing": "Manquant",
  "The installation code is eight letters, printed in the console's logs.":
    "Le code d'installation fait huit caractères, affichés dans les logs de la console.",
  "An email address is what the console will ask you for.":
    "C'est une adresse e-mail que la console vous demandera.",
  "A password of 8 characters at the least.": "Un mot de passe de 8 caractères au moins.",
  "The two passwords are not the same.": "Les deux mots de passe ne sont pas les mêmes.",
  "Claude Code CLI (subscription)": "Claude Code CLI (abonnement)",
  "{{name}} — signed in as {{account}}": "{{name}} — connecté en tant que {{account}}",
  "{{name}} — not signed in": "{{name}} — pas connecté",
  "{{name}} — {{key}}, sessions on OpenRouter": "{{name}} — {{key}}, sessions sur OpenRouter",
  "{{name}} — {{key}}, sessions still on the CLI":
    "{{name}} — {{key}}, sessions toujours sur le CLI",
  "Board kept by Ponos, without Notion": "Tableau tenu par Ponos, sans Notion",
  "Notion workspace “{{workspace}}”": "Espace Notion « {{workspace}} »",
  "Notion workspace “{{workspace}}” — {{count}} ticket": "Espace Notion « {{workspace}} » — {{count}} ticket",
  "Notion workspace “{{workspace}}” — {{count}} tickets": "Espace Notion « {{workspace}} » — {{count}} tickets",
  "A Notion workspace": "Un espace Notion",
  "Notion workspace — {{count}} ticket": "Espace Notion — {{count}} ticket",
  "Notion workspace — {{count}} tickets": "Espace Notion — {{count}} tickets",
  "{{model}} by default, chosen per ticket by the rules":
    "{{model}} par défaut, choisi par ticket selon les règles",
  "Chosen per ticket by the rules": "Choisi par ticket selon les règles",
  "{{model}} for every ticket": "{{model}} pour tous les tickets",
  "The CLI's default model for every ticket": "Le modèle par défaut du CLI pour tous les tickets",
  "GitHub account": "Compte GitHub",
  "Not signed in": "Pas connecté",
  "{{root}} — {{count}} repository found": "{{root}} — {{count}} dépôt trouvé",
  "{{root}} — {{count}} repositories found": "{{root}} — {{count}} dépôts trouvés",
  "None — nothing reaches your phone": "Aucun — rien n'atteint votre téléphone",
  "Environment": "Environnement",
  "Container — Ponos {{version}}": "Conteneur — Ponos {{version}}",
  "Machine — Ponos {{version}}": "Machine — Ponos {{version}}",
}
