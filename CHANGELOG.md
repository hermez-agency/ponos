# Changelog

What changed, release by release, in words a user of the runner would use — not
in commit subjects. Every entry answers "what can I do today that I could not do
yesterday", and the ones that matter most are the ones that change a habit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the versions follow [semantic versioning](https://semver.org/): the **minor**
number moves when the runner gains something, the **patch** number when it stops
getting something wrong, and the **major** number when an installation needs a
hand to keep working — a configuration key that changed name, a Notion property
that has to exist, a command that went away.

`Unreleased` is where work lands as it is merged. It becomes a version when
somebody cuts a release; see `.claude/skills/release/SKILL.md`.

## [Unreleased]

### Added

- La page d'un projet a un onglet « Récurrences » (`&tab=schedules`) : ses récurrences, en tableau ou en calendrier, et « Nouvelle récurrence » avec le projet déjà choisi. Sous ses chiffres, un encart « Objectifs » montre les objectifs actifs qui le nomment, chacun avec son avancement, et mène à la page Objectifs filtrée sur lui. Un projet seulement déclaré dans `config.toml` n'a ni l'un ni l'autre, et dit pourquoi il n'a pas de « Nouveau ticket » : « Ce projet n'a pas de page : créez-la pour y rattacher des tickets », avec un lien qui ouvre « Nouveau projet » sur son nom et son chemin — créer la page sous ce nom n'est plus refusé comme un nom déjà pris.
- La palette Ctrl+K propose toutes les créations : « Nouvelle idée », « Nouvel objectif », « Nouvelle récurrence » et « Nouvelle session » rejoignent « Nouveau ticket » et « Nouveau projet », chacune ouvrant son formulaire (la session, une conversation vide dans le panneau). La page Sessions y est parmi les pages. Sur la page d'un projet, l'entrée devient « Nouveau ticket pour <projet> », le projet déjà choisi dans le formulaire. Et la touche N, hors d'un champ et sans fenêtre ouverte, ouvre « Nouveau ticket » sans passer par la palette, qui l'affiche à côté de l'entrée.
- Le connecteur MCP parle d'objectifs : l'outil `list_goals` (lecture) les liste avec leur statut, leur échéance et leur avancement, `create_task` rattache la tâche à un objectif donné par son nom (sans tenir compte de la casse) ou son identifiant — un objectif inconnu est refusé avec la liste des objectifs connus —, et `list_tasks` comme `get_task` disent l'objectif de chaque tâche.
- La page d'un objectif liste ses tickets, groupés par colonne dans l'ordre du board, chacun avec son numéro court et un lien qui ouvre sa fenêtre par-dessus la page ; un bouton « + Ticket » ouvre le formulaire « Nouveau ticket » avec l'objectif déjà choisi. L'API des objectifs donne pour cela la colonne et le numéro court de chaque ticket lié (`linked`).
- La CI d'un projet peut tourner sur la machine avant l'ouverture de la pull request : une fois que la session a commité, la commande déclarée dans l'onglet Réglages du projet (`make ci`, `npm run ci`…) — ou, à défaut, ses workflows GitHub via `act` s'il est installé — tourne dans Docker ; rouge, elle repart vers la même session pour être corrigée, puis relancée, jusqu'à `runner.local_ci_attempts` fois (3). La pull request ne s'ouvre que si elle passe ; sinon le ticket est bloqué (`merge.local-ci-failed`) avec la question. Le ticket n'en garde qu'une ligne (« CI locale : OK », « CI locale : échec, corrigé en 2 tentatives »), sans les logs. Désactivée par défaut (`runner.local_ci`), activable globalement (Code et dépôts › CI locale avant pull request) ou par projet, et seulement si Docker répond : les réglages disent « Docker détecté » ou « Docker absent », et grisent l'option sans lui ; `ponos doctor` le vérifie aussi. `runner.local_ci_concurrent` (1) borne le nombre de CI locales simultanées ; conteneurs, réseaux et volumes de compose sont nommés `ponos-ci-<ticket>` (`COMPOSE_PROJECT_NAME`, `PONOS_CI_NAME`) et supprimés à la fin de chaque passage. La CI de GitHub reste le contrôle final.
- Une nouvelle conversation se démarre depuis le panneau de discussion : le crayon, avec son infobulle, ou Ctrl+Shift+O (⌘⇧O sur Mac), ouvre une conversation vide sur le modèle déjà choisi ; l'horloge à côté liste les dernières conversations, avec leur titre et leur date, pour rouvrir l'une d'elles, et mène à la page Sessions pour les autres.
- La clé API Anthropic se teste depuis les réglages : un bouton « Tester la connexion » à côté du champ « Anthropic API key » (Modèles › Fournisseur et modèle par défaut) demande à Anthropic si la clé tapée — ou, champ vide, celle enregistrée ou donnée par `ANTHROPIC_API_KEY` — fonctionne, sans rien enregistrer. Jusqu'ici, seule la première connexion vérifiait la clé.
- Un ticket en cours se met en pause ou s'abandonne depuis la console, sur sa carte comme sur sa fiche. **Mettre en pause** arrête proprement la session, enregistre le travail non commité dans un commit de sauvegarde, garde la worktree et passe le ticket en *Paused* (« En pause ») : le runner ne le reprend jamais seul, même si on commente dessous. **Reprendre** le remet en *Ready* et la session suivante repart de la worktree et du travail existants. **Abandonner**, après confirmation, arrête la session, supprime la worktree (sans résidu) et passe le ticket en *Cancelled*. Les deux marchent aussi quand la session est déjà morte ou bloquée, et laissent une ligne courte sur le ticket (« Mis en pause », « Abandonné »). Le nouveau statut `paused` s'ajoute au select de la base (`ponos init`), se nomme dans `[notion.status]` et se vérifie avec `ponos doctor`.

- La première connexion d'une installation neuve (image Docker, template Dokploy) ouvre l'assistant : le board en Markdown étant utilisable d'emblée, rien n'indiquait qu'il restait des réglages à faire et la console s'ouvrait sur un tableau vide. L'assistant (Claude, Notion, GitHub, premier projet, canaux) se propose maintenant jusqu'à ce qu'on ait atteint son récapitulatif — une seule fois ; ensuite les réglages se modifient dans les paramètres.
- Les idées se cherchent toutes seules, selon un planning réglé depuis le bouton « Réglages » de l'écran Idées (ou `runner.ideas_*` dans `config.toml`) : désactivé par défaut, toutes les 4 h, tous les jours à une heure, toutes les semaines un jour et une heure, toutes les N heures ou selon une expression cron, sur le moteur des récurrences et le fuseau de la machine. Tous les projets (ceux ajoutés plus tard compris) ou une sélection, l'espace de travail à part, et chaque projet peut se désactiver ou s'activer depuis sa page. Garde-fous : idées par passe et par projet (10), projet sauté au-delà de N idées nouvelles non triées (20, dit dans le journal), plafond de coût par passe, modèle, notification facultative sur les canaux. L'écran Idées rappelle la prochaine et la dernière passe, la vue Calendrier des récurrences dessine les passes à venir en lecture seule, et `ponos doctor` vérifie le planning. Les passes tournent dans la console ; le bouton « Ponos, trouve-moi des idées » reste disponible à tout moment.
- Une nouvelle identité : un logo et une mascotte simplifiée. Le logo — la flamme et l'écran du robot dans le cadre du symbole Hermez, en clair et en sombre — devient le favicon (il suit le thème du système), l'icône de l'app installée, de l'écran d'accueil iOS, du bureau, des notifications et du template Dokploy, et reste lisible en 16 px. La mascotte passe à plat : trois formes, deux oranges, un visage par état sur son écran (sept états, les mêmes noms), sans dégradé ni tunique, et des animations sobres — respiration, clignement, flamme qui ondule — qui s'arrêtent sous `prefers-reduced-motion`.
- L'écran Récurrences s'ouvre en deux colonnes, comme les Projets : la liste à gauche (règle, interrupteur, prochaine exécution, projet, badge en cas de problème), et à droite la récurrence choisie — ses tickets, leur coût total et moyen, leur durée moyenne, le taux de réussite, un graphique par semaine, puis les onglets Tickets, Exécutions et Réglages, modifiables sur place. La sélection et l'onglet sont dans l'adresse ; sur mobile, la récurrence s'ouvre en plein écran avec un bouton retour. Ponos garde désormais chaque exécution d'une récurrence dans `ponos.db` — le ticket créé, ou pourquoi aucun (sautée, erreur) ; les tickets d'avant sont retrouvés par l'historique et par leur titre daté. Le projet d'une récurrence se choisit dans son formulaire.

### Changed

- Les refus du serveur s'affichent en français dans une console réglée en français : objectifs, récurrences, brief d'un projet, ménage et réglages (« Rien à modifier. », « Une passe est en cours — réessayez une fois qu'elle sera terminée. », « « Bug » apparaît deux fois. »…), au lieu de la phrase anglaise du serveur. Une réponse sans message dit « Le serveur a répondu 500 » plutôt que « 500 ». Un refus que la console ne connaît pas reste affiché tel que le serveur l'a écrit.
- Les gestes de la console qui effacent demandent d'abord, et chaque bouton réseau dit où il en est : « Faire le ménage » (Réglages › Général) ouvre une confirmation qui rappelle la règle de rétention et ce qui peut partir au plus, « Jeter » la file des messages en attente demande confirmation puis dit « Messages jetés », et une erreur sur cette file porte un titre au-dessus du message. « Resynchroniser maintenant » fait tourner son icône et se désactive pendant la relecture, puis dit « Tableau relu ».
- La console ne relit plus Notion à chaque page ouverte : le tableau de bord, la page Objectifs, les statistiques et la recherche d'idées reprennent le board que la console a lu il y a moins de `web.poll_seconds` (15 s par défaut), au lieu de refaire chacun la même requête sur la base des tickets — et de relire tous les runs, l'historique et le journal de synchro pour habiller les mêmes cartes. Un ticket créé, déplacé ou modifié depuis la console fait relire Notion à la demande suivante. Deux lectures simultanées à l'ouverture ne font plus chacune une lecture complète : la seconde attend la première. Ouvrir le tableau de bord puis les statistiques coûte une requête Notion au lieu de deux.

### Fixed

- Objectifs : « Nouvel objectif » n'est plus proposé dans un espace sans base Objectifs — le formulaire, une fois rempli, se faisait refuser à l'enregistrement. La liste vide le dit (« Aucun objectif. », ajoutez une base dans Notion) et, avec une base, propose le bouton « Nouvel objectif » au lieu de renvoyer vers Notion.
- Deux enregistrements simultanés de la configuration — deux onglets des réglages, ou un onglet et la CLI — ne s'effacent plus l'un l'autre : chacun attend son tour sous un verrou (`.config.toml.lock`), là où le second remplaçait le fichier par une copie faite avant le premier, dont les changements disparaissaient sans un mot. Et `ponos init` comme `ponos notify pair` n'écrivent plus `config.toml` en place : ils passent par le même enregistrement que la console, qui remplace le fichier d'un coup et garde l'ancien dans `config.toml.bak` — une coupure en pleine écriture ne laisse plus une configuration tronquée qui empêche le runner de démarrer.
- En `storage.mode = "both"`, un conflit n'est plus gagné à tort par le fichier Markdown : Notion arrondit son heure de modification à la minute, le fichier la garde à la microseconde, et une page modifiée dans Notion à 10:05:50 (vue comme 10:05:00) perdait contre un fichier modifié à 10:05:30. Les deux heures sont maintenant comparées à la minute ; dans la même minute, Notion l'emporte, et le journal dit que l'égalité a été tranchée (« same minute, a tie goes to Notion »).
- `uninstall.sh` défait tout ce que `install.sh` a posé : sur un Mac, les agents launchd `app.ponos.run` et `app.ponos.web` sont déchargés puis supprimés (ils continuaient de relancer un binaire effacé) ; la console lancée en arrière-plan sans systemd ni launchd est arrêtée (`install.sh` garde son PID dans `web/serve.pid`) ; le gestionnaire `ponos://` et son association `xdg-mime`, les icônes `hicolor` et les drop-ins `ponos*.service.d` sont retirés ; et les portes Tailscale (serve et Funnel) sont fermées par `ponos tailscale disable` avant que le binaire disparaisse.
- L'audit technique d'octobre 2026 n'est plus publié sur the-ponos.app : il était rangé sous `docs/`, la racine du site, et servi tel quel à `/audit-technique-2026-10.md`. Il vit maintenant dans `notes/`, et un test refuse tout Markdown sous `docs/` comme toute entrée à sa racine que le site ne sert pas exprès.
- Une récurrence dont l'occurrence n'a pas pu être prise ne crée plus de ticket : quand Notion refuse d'écrire `Next` et `Last` sur sa ligne (erreur 5xx, page verrouillée) ou que `Next` est une colonne calculée (formule, rollup) que le runner ne peut pas écrire, `Next` restait dans le passé et chaque passe recréait le même ticket. L'occurrence attend maintenant que l'écriture passe, et `ponos doctor` signale une colonne `Next`, `Last` ou `Last ticket` non inscriptible.
- Un ticket renommé entre deux tentatives reprend sa branche : elle est retrouvée par l'identifiant court du ticket (localement, sinon sur `origin`), quel que soit son titre actuel. Jusqu'ici, le nouveau titre donnait une nouvelle branche — le ticket échouait sur l'ancien worktree (« still holds work from an earlier attempt ») ou repartait de la base en ouvrant une seconde pull request.
- Deux tickets du même dépôt lancés ensemble (`max_concurrent_per_project` vaut 2) ne se disputent plus son `.git` : `fetch`, la création et la suppression des worktrees, le `prune`, la suppression d'une branche et le rejeu d'une branche poussée attendent leur tour, dépôt par dépôt. Ils échouaient de temps à autre sur « cannot lock ref », « could not lock config file », ou un `prune` qui retirait une worktree en cours de création.
- Une session coupée par `timeout_minutes`, arrêtée ou relancée ne coûte plus 0 $ dans le rapport et l'historique : le coût, les tours et la durée annoncés par son dernier événement sont gardés, et une session relancée après avoir été tuée — ou repartie de zéro faute de pouvoir être reprise — additionne ce qu'ont coûté ses deux tentatives au lieu de ne garder que la seconde.
- Une réponse de plus de 100 blocs n'est plus publiée à moitié dans Notion : quand un lot est refusé en cours d'écriture, les blocs déjà écrits sont retirés avant que le ticket passe en Échec. La tentative suivante écrivait jusqu'ici sa réponse entière sous une réponse tronquée.
- Un ticket dont la réclamation ou la fusion échoue sur le board (une erreur 400 de Notion, par exemple) échoue seul : la passe ne s'arrête plus en attendant les sessions encore en cours — parfois des heures, verrou tenu — sans enregistrer leur résultat, qui manquait alors dans `ponos history` et dans le plafond quotidien. Elle continue de remplir les places et d'enregistrer chaque fin.
- La fenêtre d'un ticket ne propose plus de choisir son objectif sur un board sans colonne « Objectif » : le sélecteur n'y apparaît plus, au lieu d'échouer sur un message d'erreur à chaque choix. Comme dans le formulaire « Nouveau ticket », il n'est là que si le board peut relier un ticket à un objectif.
- La page Objectifs se met à jour toute seule : un objectif créé, modifié ou archivé dans un autre onglet, un ticket lié depuis sa fenêtre, ou un ticket d'un objectif qui change de colonne (passé en Done, par exemple) relit la liste et la page ouverte d'un objectif — « n sur m tickets faits » avance sans recharger la page. Jusqu'ici, les objectifs n'étaient relus qu'en naviguant.
- Modifier un objectif sans priorité n'y écrit plus 50 : une priorité laissée vide dans le formulaire ne touche plus la colonne. Et un objectif dont la colonne « Priorité » est encore un select (« High ») s'enregistre de nouveau : la console lit sa priorité en score de 0 à 100 (« High » vaut 75) au lieu de refuser le mot.
- En `storage.mode = "both"`, « Configurer » sur la vérification des colonnes du tableau de bord ajoute enfin les propriétés manquantes côté Notion, au lieu d'échouer : la correction cherchait `add_properties` sur le miroir, qui n'en a pas. Trouvé en passant `health.py` en mypy strict.
- Le sélecteur de modèle de la conversation se lit enfin : le nom du modèle OpenRouter ou Claude s'affiche en entier sur sa propre ligne, l'identifiant technique (complet au survol) et le prix (« $0.29 / $1 par million de tokens ») passent dessous en petit et en gris, et le menu, plus large, ne dépasse plus de l'écran.
- Une récurrence se rattache enfin à un projet depuis la console : son formulaire, à la création comme à l'édition, n'avait pas de champ Projet, si bien que chacun de ses tickets naissait sans projet et revenait en document — une récurrence de code ne s'écrivait que dans Notion. Le projet se choisit comme pour un nouveau ticket, parmi ceux qui ont une page, et une récurrence créée depuis la liste filtrée sur un projet est d'emblée celle de ce projet.
- En `storage.mode = "both"`, un ticket modifié à la main dans son fichier Markdown (`$EDITOR`, `sed`, un merge git) arrive enfin dans Notion : la synchro ne regardait que la ligne `edited` du front matter, qu'un éditeur ne touche pas, si bien que la modification restait invisible puis était écrasée sans trace au prochain changement côté Notion. Chaque tampon garde maintenant une empreinte du fichier (propriétés et corps) ; une modification faite des deux côtés est journalisée comme un `conflict`, datée côté fichier par son heure de modification.
- Un board Markdown ne perd plus d'écriture quand le runner et la console écrivent le même ticket : un statut déplacé depuis la console pendant que le runner ajoutait son rapport pouvait disparaître (le dernier qui écrit gagnait), et un lecteur tombé au milieu d'une écriture lisait un fichier à moitié vide. Chaque modification se fait désormais sous un verrou sur le dossier du board, et le fichier est remplacé d'un coup plutôt que réécrit sur place.
- Une PR validée mais en retard sur sa base n'est plus fusionnée dans la seconde qui suit son rejeu : juste après le push, GitHub n'a encore déclaré aucun check, et cette liste vide passait pour « rien de rouge » — sur un dépôt sans protection de branche, le commit rejoué arrivait sur `main` sans avoir été testé. Sur un dépôt qui a une CI (`.github/workflows`), le ticket reste maintenant en *Validé* et la passe suivante fusionne ce que la CI a vu.
- Les permissions par défaut d'une installation neuve ne sont plus celles du mainteneur : plus de Dokploy, de compte GitHub ni de prénom d'une personne en particulier dans `[permissions]`, dans `config.example.toml` ni dans le prompt de chaque session (« l'utilisateur » à la place). Un ticket visant le mauvais dépôt se règle pour le propriétaire GitHub du projet et ceux que `[github]` nomme. Un `config.toml` qui a déjà écrit ses listes les garde tel quel.
- Une réponse publiée dans Notion n'est plus tronquée : un bloc de code ou un paragraphe de plus de 1 900 caractères (un `ANSWER.md`, une récurrence, le contexte d'un ticket) perdait tout ce qui dépassait, sans un mot. Le texte est maintenant découpé en morceaux dans le même bloc, puis continue dans les blocs suivants au-delà de 100 morceaux.
- Le plafond quotidien (`budget.daily_usd`) compte enfin toutes les sessions payées : celles qui nomment, classent ou donnent un sous-type à un ticket, celle qui répare la CI d'une PR, et celles dont le ticket n'a jamais eu sa ligne d'historique (Notion injoignable, runner planté juste après) passaient à côté. Chaque session est maintenant inscrite à sa fin, dans une table que lit le plafond ; l'historique du jour est repris à la mise à jour. Une publication à validation forcée additionne aussi ses deux sessions (préparation et publication) dans la colonne *Cost* et dans l'historique, au lieu de ne garder que la seconde.
- Une publication validée dont le post était parti ne revient plus en *Ready* quand Notion tombe juste avant l'écriture de « Done » : la note qui dit « pris dans Validé » n'est plus effacée qu'une fois le statut final écrit, et une coupure réseau ne l'efface plus. Au passage suivant, le ticket passe en *Bloqué* avec la question « publication interrompue » au lieu d'être publié une seconde fois.
- Un ticket sorti de *Ready* pendant sa préparation (clone, sessions de nommage, de classification ou de sous-type : plusieurs minutes) n'est plus lancé. Le runner remarquait déjà le déplacement et n'écrivait pas « En cours » par-dessus, mais démarrait quand même la session, qui pouvait ouvrir une PR pour un ticket annulé ; il l'abandonne maintenant, sans commentaire d'échec, et le dit dans le journal.
- Une erreur du board dans les étapes de tête d'une passe n'arrête plus tout le runner : une base Récurrences retirée de l'intégration (404), ou un ticket « En cours » ou « En revue » dont la page refuse l'écriture, coûtent une ligne de journal, et les tickets Ready démarrent quand même. Dans le ménage des tickets abandonnés et la clôture des PR fusionnées, un ticket refusé n'empêche plus de traiter les autres. Un réseau injoignable arrête toujours la passe, comme avant.
- Les objectifs s'écrivent depuis la console : « Nouvel objectif » ouvre un formulaire aligné sur la base Objectifs (nom, description, « Terminée quand », échéance, statut, priorité, projets), chaque champ d'un objectif se modifie depuis sa carte ou son détail, ses tickets se lient et se délient depuis l'objectif ou, d'un ticket, par le choix de son objectif sous le titre, et l'archivage (corbeille de Notion) demande confirmation. L'avancement se recompte après chaque écriture, et une écriture refusée s'affiche telle quelle. Un tableau de fichiers Markdown a désormais, lui aussi, son dossier `goals/`.
- Sur mobile, la barre de navigation du bas affiche ses libellés en entier (« Dashboard », « Récurrences », « Objectifs », « Sessions ») au lieu de les tronquer.
- Une version fusionnée sur `main` reçoit son tag et sa release toute seule : la 0.2.0 était restée sans tag, donc sans release GitHub ni image `:0.2.0` / `:latest`. La CI pose désormais le tag `v<version>` quand il manque et lance le workflow de release.
- Une récurrence se supprime depuis la console : une corbeille sur chaque ligne de la liste, sur chaque carte, dans la fenêtre de la récurrence et dans la fiche du calendrier, après confirmation, et une sélection multiple pour en retirer plusieurs d'un coup. La page part dans la corbeille du board (Notion ou dossier `trash/`), plus aucun ticket n'en naît, et ceux déjà créés restent en place.
### Security

- La limite de tentatives de la console ne se contourne plus en faisant varier `X-Forwarded-For` : l'en-tête n'était cru que d'un pair local ou privé, mais n'importe lequel — le port Docker publié (la passerelle du pont), un autre conteneur du réseau Dokploy qui joint la console sans Traefik, une machine du LAN — pouvait annoncer une nouvelle adresse à chaque essai et n'attendait jamais. Il n'est plus lu que d'un proxy déclaré dans `web.trusted_proxies` (cette machine par défaut, d'où relaie `tailscale serve`), ou par `PONOS_WEB_TRUSTED_PROXIES` dans un conteneur ; sinon l'adresse comptée est celle du pair. Derrière Traefik, déclarez son adresse — sans elle, les erreurs de tous les visiteurs se comptent ensemble. `ponos doctor` signale une entrée qui n'est ni une adresse ni un réseau.
- Une session Claude ne reçoit plus les secrets propres au runner : le mot de passe et le jeton de la console, les jetons de Notion, de Telegram et de Slack, les clés Anthropic et OpenRouter et le jeton GitHub de Ponos sont retirés de l'environnement qu'elle hérite — en Docker, un `env` lancé par une session les écrivait en clair dans sa transcription, le ticket et la pull request. Elle garde ce que le coffre accorde à son projet et ce que son fournisseur lui donne. Chacun de ces secrets, lu dans l'environnement ou dans `secrets.env`, est aussi masqué partout où le runner écrit.

### Changed

- `ponos.db` ne grossit plus sans fin : le ménage quotidien y applique `log_retention_days` comme aux logs — les étapes des sessions de cet âge partent (la session reste, avec son issue et son coût), comme le journal de synchronisation, les appels MCP et les transitions terminées —, puis le fichier est compacté dès qu'un quart en est libre et son `-wal` vidé. `ponos doctor` donne la taille de la base et de son `-wal`.
- Le bandeau d'état de l'installation ne refait plus toutes ses vérifications à chaque affichage du tableau : `GET /api/health` (`claude --version`, `gh auth status`, la lecture du board et de chaque projet — 10 à 25 s sur une vraie installation) garde sa réponse cinq minutes, qui revient alors en quelques millisecondes. « Revérifier » (`?fresh=true`), une correction « Configurer » et l'enregistrement des réglages vérifient de nouveau sur-le-champ.
- Ouvrir un ticket ne relit plus toute la base locale : ses sessions, son temps de travail et sa cause de blocage se cherchent par index (une migration ajoute ceux des idées, de l'historique et des notifications), quelques microsecondes au lieu de quelques millisecondes sur 20 000 sessions. `ponos logs --runs <8 caractères>` donne les sessions du dernier ticket qui finit ainsi, et plus celles de tous les tickets qui partagent ces caractères.
- Une mise à jour qui migre `ponos.db` n'empêche plus de revenir à la version précédente : avant la première migration manquante, le fichier est copié tel quel sous `ponos.db.v<N>.bak` (N, son numéro de schéma d'alors, par la sauvegarde de SQLite même pendant qu'un autre processus écrit), et seules les trois dernières copies sont gardées. `ponos doctor` nomme la plus récente et la commande qui la remet en place — y compris quand l'ancienne version refuse une base « written by a newer version ».
- L'en-tête de la console compte les tickets traités et additionne leur coût en une requête SQL (`state.totals()`, que `ponos status` partage) au lieu de décoder les 10 000 dernières lignes de l'historique à chaque lecture : ~39 ms → ~2 ms sur 10 001 lignes, et le compte comme la dépense ne plafonnent plus à 10 000 tickets. Le dashboard ne lit plus `/api/state` qu'une fois en s'ouvrant : l'état de la mise à jour, que le flux rejoue à chaque connexion, ne déclenche plus une seconde lecture.
- Les statistiques du tableau de bord se recalculent sans attendre quand on change de période ou de projet : elles reprennent le board que la console vient de lire pour sa vue en direct (âgé d'au plus deux fois `web.poll_seconds`) au lieu de refaire une requête Notion à chaque fois, et lisent l'historique dans les colonnes de `ponos.db` plutôt qu'en décodant chaque ligne. Sur une vraie console, un changement de période passe de 0,4 à 17 s (selon Notion) à une douzaine de millisecondes.

- Lire la file ne lit plus les commentaires des tickets que le runner n'a jamais touchés : seuls ceux dont la colonne `Runner` porte le nom de la machine, ou dont il se souvient d'avoir parlé sur la page, sont interrogés pour savoir si une réponse les réveille. Mesuré sur un backlog de 200 tickets jamais lancés, plus un de cette machine, un d'une autre et un connu de la mémoire des conversations : 202 requêtes de commentaires par lecture de file avant, 2 après.
- Le rapport en direct d'un ticket (le bloc « En cours » et la colonne `Progress`) s'écrit depuis un fil à part, et plus depuis la boucle qui lit la session : un Notion lent ou qui répond 429 n'arrête plus la lecture de sa sortie, donc plus la CLI derrière un tube plein pendant que son délai court. Ce qui s'accumule pendant l'attente part en une écriture quand Notion répond, dans une file bornée. Mesuré sur une session de 50 étapes en 5 s face à un Notion à 3 s par requête : la lecture passait de 377 s à 5 s.
- Un objectif terminé se clôt au lieu de partir à la corbeille : sa page propose « Atteint » et « Abandonné », qui écrivent son statut et gardent ses tickets et son décompte (« 12 sur 12 faits »). La liste des objectifs n'affiche plus par défaut que les actifs (sans statut, ou « actif ») ; le filtre de statut propose « Tous les statuts » et chaque statut pour revoir les autres. La mise à la corbeille, en retrait, s'appelle maintenant « Supprimer », et sa confirmation dit qu'il s'agit d'une suppression.

- Le choix de l'objectif d'un ticket — dans « Nouveau ticket » comme dans la fenêtre d'un ticket — ne propose plus que les objectifs encore actifs (statut vide, « Actif » ou « En cours ») : ceux atteints ou abandonnés n'y sont plus, sauf l'objectif que le ticket sert déjà. Ceux du projet choisi viennent en premier, les autres suivent. La liste des objectifs dit pour cela si chacun est actif (`active`), et les choix d'un nouveau ticket portent les projets de chaque objectif.
- Quota épuisé, le runner ne s'arrête plus tout entier jusqu'au retour des crédits : comme sous la réserve, il fusionne les pull requests validées et vertes, passe en Fait celles fusionnées et remet d'aplomb les tickets abandonnés par un plantage ; seules les sessions attendent, et les tickets prêts sont cochés « en attente de crédit ».
- Une carte « En cours » dit dans quelle phase est son ticket entre deux sessions, et depuis quand : « rebase sur main · depuis 3 min », « lance la CI en local », « attend la CI de la PR #371 », « répare la CI de la PR #371 », « résout les conflits avec main ». Elle restait jusqu'ici sur « démarrage… » pendant toute l'attente de la CI ou d'un rebase, parfois plus d'une heure. « démarrage… » ne dure plus que deux minutes sans étape de la session ; au-delà, la carte dit « la session n'a encore rien écrit · depuis 5 min ». Le runner note chaque phase dans `ponos.db` (table `phases`), que la console lit avec le tableau.
- Une pull request dont la fusion n'a pas eu lieu n'a plus pour seul geste « Rendre prêt », qui relançait une session payante : bloquée sur une CI rouge ou un refus de GitHub, sa carte propose **Réessayer la fusion** (retour dans Validé, le runner redemande la fusion à sa passe suivante, sans session) et **Renvoyer en revue** ; dans Validé, elle propose aussi **Renvoyer en revue**. La ligne de la carte dit « Pas fusionnée : CI rouge » au lieu de « laissée en relecture », qui restait affichée dans Validé, et elle est vidée quand le ticket passe en bloqué. Un ticket revalidé pendant une longue passe est fusionné par elle, plus seulement à la suivante.
- La ligne d'avancement d'un ticket en cours (colonne `Progress`, carte « Ponos travaille… », bloc « En cours ») suit `runner.language` : la consigne de langue donnée à la session couvre désormais aussi ce qu'elle dit entre deux étapes, en phrases courtes et complètes plutôt qu'en notes en anglais (« Now delivery around the claim. »). Le texte reste celui du modèle, affiché tel quel ; le README le dit.
- Le tableau allège la colonne « Prêt » : la ligne « en attente : son projet occupe déjà… » ne se répète plus sur chaque carte (le runner la garde dans son journal). L’en-tête « En cours » dit où en est la file, « 5/5 » : le maximum est `runner.max_concurrent`, et il vire à l’ambre quand la file est pleine.
- La conversation de la console montre ce que Ponos fait pendant qu'il le fait : ses phrases arrivent au fil de l'eau, chaque outil qu'il appelle (lecture, commande…) s'affiche avec ses arguments, son état et ce qu'il a répondu, et une commande qui échoue le dit. Une conversation rouverte depuis l'historique se relit telle qu'elle s'est déroulée. Sous le capot, le panneau est `useChat` de TanStack AI, dessiné par les composants de chat de Brand Assets, et le serveur parle AG-UI sur `/api/chat/agui` — que n'importe quel client AG-UI peut aussi appeler.
- Le template Dokploy expose tout ce qu'un serveur peut recevoir — la clé OpenRouter, les bots Telegram et Slack, le fuseau horaire (`TZ`) en plus de l'abonnement Claude, de la clé Anthropic, de GitHub et de Notion —, chaque variable avec son commentaire. Le service tourne sous l'utilisateur `ponos`, avec un plafond mémoire de 4 Go, et sa fiche du catalogue décrit Ponos tel qu'il est : un harnais qui exécute des tâches, code ou non. Le README et the-ponos.app décrivent le même parcours en trois étapes, catalogue d'abord (*Templates › Ponos › Create*), import Base64 en secours, avec un bloc « Install on a server, with Dokploy » sur le site et un bouton en tête du README.
- `ponos doctor` et la bande « État de l'installation » du tableau de bord posent désormais exactement les mêmes vérifications : tout ce que `doctor` contrôlait seul (outils, App et jeton GitHub, fournisseur Claude, coffre `[vault]`, environnement Python, notifications, console, dépôts du dossier de travail, disque, mémoire, version, base locale, secrets, validation automatique, modèles, statuts Annulé et Brouillon, types, récurrences, commentaires) apparaît aussi sur la bande, en français, avec sa cause et la marche à suivre. `doctor` les range par groupe (Tableau, GitHub, Claude, Projets, Machine, Réglages), ne compte plus deux fois un même problème, et va au bout même quand une vérification échoue au lieu de s'arrêter avant le tableau ; ses lignes en gris décrivent un réglage et n'apparaissent pas sur la bande.
- L'écran Idées s'ouvre sur l'onglet Nouvelles, pour trier sans cliquer d'abord. Un filtre déjà dans l'adresse l'emporte, « Tout » reste un choix qu'on garde, et sans idée nouvelle la liste le dit avec un lien vers « Tout ».
- Le schéma `/openapi.json` de la console décrit maintenant la réponse de chaque route qui répond du JSON — les écritures (tickets, conversation, récurrences, GitHub…), la santé de l'installation, l'historique, le journal du service et toute la première connexion — et plus seulement celle des lectures. Seules les trois routes qui servent des octets (image d'un projet, fichier du board, fichier de la conversation) n'en ont pas.
- Pour qui contribue : la classe `Api` de la console n'est plus un fichier de 2 400 lignes. Elle est assemblée, comme le `Runner`, à partir de chapitres — `web/tickets.py`, `projects.py`, `creation.py`, `removal.py`, `goals.py`, `schedules.py`, `configuration.py`, `overview.py`, `upkeep.py`, `journals.py`, `discussion.py`, `ideas.py` — sur un seul état, dans `web/base.py` ; `web/api.py` dit pourquoi. La création, la suppression d'un projet et les idées ne sont plus des objets à part qui réimportaient `Api`, et les modules nouveaux sont vérifiés par mypy en strict. Les routes, leurs réponses et le schéma `/openapi.json` n'ont pas changé.
- La fenêtre « Débloquer » (et « Décider ») finit sur la mascotte qui célèbre au lieu d'une simple coche, avec une petite apparition désactivée sous `prefers-reduced-motion`. Le bouton « Fermer ↵ » a le focus : Entrée ferme la fenêtre à la fin, et ne fait rien pendant la série.

## [0.2.0] - 2026-10-22

### Added

- Une installation en une commande, et une première connexion guidée. L'installeur vérifie la machine et
  nomme d'un coup tout ce qui manque, avec la commande qui l'installe (apt-get, dnf, pacman ou brew) ; il ne pose
  plus de question dans le terminal et lance la console, puis l'ouvre dans le navigateur. La première connexion
  commence par la langue, puis mène à un premier projet et à un ticket de démonstration créé et joué aussitôt. Le
  pas Notion vérifie le jeton, et trouve seul la page partagée avec l'intégration. Le récapitulatif ajoute une ligne
  pour la machine et lance `ponos doctor`, qui affiche la commande d'installation à côté de ce qui manque.
- « Ponos travaille » revient après un déblocage : la carte d'un ticket en cours
  montre le robot au travail, et la fenêtre du ticket rouverte — rechargement
  compris — l'affiche tant que la session tourne.
- La console a une page **Objectifs** : une carte par objectif de la base
  `Objectifs`, avec son échéance, son critère et « n sur m tickets faits »,
  filtrable par statut et par projet. L'avancement est compté sur les tickets
  du tableau, pas lu dans un rollup Notion. La fenêtre d'un ticket rattaché
  montre son objectif, en lien vers sa page, et « Nouveau ticket » propose d'en
  choisir un (facultatif, vide par défaut).
- Les idées lisent les caps du moment : la proposition d'un lot et la notation
  reçoivent, sous « Les caps du moment », le nom, le `Critère` et l'`Échéance`
  de chaque objectif actif (`Statut` vide, `Actif` ou `En cours`) — ceux dont la
  relation `Projets` contient le projet, ou tous sur l'espace de travail. La
  grille de notation ne change pas ; sans cap actif, le prompt reste celui
  d'avant, au caractère près.
- Un ticket peut pointer un objectif : la colonne `Objectif` (une relation vers
  la base `Objectifs` du workspace) met dans son prompt le nom du cap, le corps
  de sa page, son `Critère` et son `Échéance`, entre le projet et le rôle. Sans
  objectif, le prompt reste celui d'avant, au caractère près. `ponos doctor`
  signale aussi deux réglages de `[notion.properties]` qui désignent la même
  colonne — `agent = "Agent"` à côté de `role`, par exemple.
- Le choix du modèle d'un ticket (nouveau ticket, fiche, « autre modèle » d'un
  ticket bloqué, récurrences) est le sélecteur du chat : les modèles Claude, et
  avec une clé OpenRouter son catalogue avec une recherche, les modèles récents,
  le prix au million de tokens et un badge « sans outils » pour ceux que Claude
  Code ne saurait pas faire travailler. Un ticket dont le modèle est un slug
  `vendor/model` tourne sur OpenRouter ; sans clé, il se bloque en le disant
  (`access.credentials`) au lieu d'échouer dans Claude Code.
- **The blocked tickets, one after another.** "Unblock (N)" in the heading of the Blocked column — and "Decide (N)"
  in that of In review, from two cards on, in Ctrl+K too, and at `/?series=blocked` or `/?series=review` — opens
  one window over the page that goes through the column: the ticket, why it stops, its choices; one sent, the next
  comes, with "Ticket unblocked — Undo". Questions first, then missing accesses, then the rest, by priority and age;
  Skip, Previous, the arrows, J and K, 1 to 9 for the session's options; a ticket moved elsewhere leaves it as it
  happens, and the end says how many were done and offers the skipped ones again.

- **The dashboard says what is misconfigured, and mends it when it can.** An "Installation status" band opens the
  page whenever something would stop a ticket: the Notion token, the Tickets and Projects databases (shared with the
  integration, with every property and status the runner uses), GitHub (App installed or `gh` signed in, access to each
  project's repository, enough rights to push and open a pull request), Claude Code (installed, recent enough, signed
  in), each project (local folder, reachable remote, known default branch) and the machine (free disk, the runner's
  timer, Telegram or Slack when they are on). Each problem comes with its probable cause and either a "Configure"
  button — which names what it will change and changes nothing until you confirm — or the exact steps, with the link
  to follow. It is checked when the page opens and again with "Recheck", and it is not drawn while everything is green.
  `ponos doctor` prints the same checks in an "Installation health" section.

### Security

- **The console's password is kept as a scrypt digest.** `secrets.env` held it as it is typed. It holds its digest
  now, written by the Settings and the first connection; an installation from before has its line rewritten by the
  next launch, and the same password keeps signing in — nobody is asked to type it again. One browser sign-in is
  asked once after the update: the sessions given before are not readable any more.
- **Guessing the door is slowed for real.** A wrong password, installation code or token used to cost a second of
  `time.sleep` in its own thread, which twenty requests sent at once all slept together. Each address now waits
  1 s, 2 s, 4 s… up to 30 s after each failure, is locked out for 15 minutes after ten, and an attempt is counted
  before it is checked: of twenty sent at once, one is looked at and the others are told `429` with a
  `Retry-After`.
- **A sign-in lasts thirty days from its last use.** The cookie it left never ran out; it is renewed while the
  browser keeps coming back and refused a month after its last use. `ponos serve --sign-out-everywhere` signs every
  browser out at once, a running console included; the token still opens it.
- **The console's pages run only their own scripts.** A Content-Security-Policy allows the bundle's files and the
  inline lines each page carries, by their hash — the sign-in and token pages lost their `onsubmit=` for it — and
  the API answers under `default-src 'none'`. With it `Permissions-Policy`, `Cross-Origin-Opener-Policy` and
  `Cross-Origin-Resource-Policy`, and HSTS once a proxy says HTTPS.
- **A repository named on a project page is checked before `gh` sees it.** Only `owner/name` is cloned or looked
  up, after a `--`; a file beside `static/` whose name begins the same way is no longer served as one of its own.

### Changed

- **Every button and menu entry starts with a capital.** « Mettre de côté », « Rouvrir », « Rendre prêt »,
  « Relancer », « Abandonner le ticket » and the other lower-case labels of the cards, the windows and the
  views now read like « Nouveau ticket » and « Fermer » beside them — « Set aside », « Reopen », « Make ready »,
  « Run again » in English.
- **Unblock and Decide: every choice numbered, none that looks already picked, the ways out apart.** All the
  choices are outlines until one is clicked — the first was drawn full, and read as chosen. Each has its number, and
  1–9 picks it in either series, Decide included. "Abandon" and "Reject" sit last, under a rule, still behind their
  note and a Confirm.
- **Small design fixes from an audit of the real console.** A toast that stays — "New version, reload?" — sits
  above the conversation button instead of on it, so that button and the drawer's send button answer again. The
  tables' "Properties" menu, their selection and the board's drag and drop say their words in French. "1 thing to
  fix", "0 of 1 ticket done" and "older than 14 days" replace their "(s)". The Decide series no longer offers keys
  1–9 it has no option for, an empty series no longer shows a full progress bar, and on a phone the hint beside
  "The brief" no longer runs over it.
- **The console's menu is the admin layout's own.** The version, the sync, "Resync" and the theme sit at the foot of
  the sidebar rather than in the top bar, which keeps the search, the bell and whether the stream is live. On a phone
  the bottom bar holds the dashboard, the projects, the ideas and the sessions, and its "More" opens the schedules, the
  goals and Settings with that same foot — every label is read whole at 360px, and there is no sideways scroll at 390px.
  The tab names the page you are on, and the console moves to
  react-resource-view 1.2.
- **Unblocking a ticket closes its window.** Answering Ponos, pressing a quick reply or running it again as it is
  sends the ticket back to Ready and takes you back to the board; if the send fails, the window stays open with the
  error.
- **A value `config.toml` cannot hold is said, with its key and its line.** The file is read against one model per
  table (pydantic): a port that is not a number, a list where a word goes, a table written as a value used to stop the
  runner with a traceback that named nothing, or to be read as something else in silence — they now stop it, the
  console's save and `ponos doctor` with `config.toml, line 12: web.port = 'eighty' — Input should be a valid
  integer`. What the runner always forgave it still forgives: a value under a key's floor is the floor, a word that is
  none of a key's choices is the default (a typo in `update_channel` is still `release`), an amount left blank is no
  limit, and a key nobody reads is left alone. One reading changes: a switch written as text, `push = "false"`, used to
  be on — any text was — and is now off; text other than true/false, yes/no, on/off, 1/0 is refused. pydantic comes
  with the version's environment, like httpx; on an installation from before environments, the first pass on the
  machine's `python3` makes it and runs no ticket, and the next pass runs in it.
- **Every service is asked again the way Notion always was.** GitHub, OpenRouter, Telegram and Slack, the pictures and
  the console's MCP test now go through one HTTP client, httpx, with Notion's policy: four attempts, the pause a "too
  many requests" asks for (a minute at most), and a request that adds something — a message, a comment — sent again
  only when it cannot have arrived. A notification refused by Telegram for going too fast is no longer lost. httpx is
  the runner's first package: an installation updates by itself, the new version's environment holding it before the
  switch, provided the machine has `uv` or, on Debian and Ubuntu, `python3-venv`; the image installs it when it is
  built.
- **The dashboard's "Installation status" band fits on one line.** Folded by default, it keeps the count of points to
  fix and "Recheck"; unfolded, each problem is one line with its button, and a toggle of its own opens the probable
  cause, the steps and the technical detail in small print. The choice is kept in the browser. A property two settings
  name (“Agent”) is listed once, what each missing property costs and Slack's errors are translated, and the raw error
  code stays in the detail ("Slack", not "slack").
- **The runner keeps a journal, and no error disappears any more.** What the runner and the console say still goes to
  the standard output — and so to `journalctl`, word for word as before — and is now also written, dated and levelled,
  to `~/.local/state/ponos/logs/ponos.log` (turned over at 1 MB, five files kept). Every error the runner or the
  console catches leaves its whole trace there, a route that answers a 500 included, and every request that comes back
  4xx or 5xx is a line. Secrets are masked on the way in: a vault's values and anything shaped like a token. Read it
  with `ponos logs --service` (`-f` to follow), or in the console's Settings, under "What this console runs on".
- **The console runs on FastAPI and uvicorn, in the environment of its version.** Same addresses, same answers,
  same door — the token or the sign-in, the `Host` check, the `X-Ponos` header on a write, the security headers —
  now one middleware in front of every route instead of checks written by hand. What a write carries is checked
  before it is used, a malformed body is refused with a `400` that says which field, and the whole API is
  described at `/openapi.json`, behind the same token. FastAPI and uvicorn are installed in each version's `.venv`
  before the version is used, by the update itself: an installation updates on its own, as before — with uv, or
  with pip, which Debian and Ubuntu ship in `python3-venv`; a machine with neither keeps the version it has and the
  update says why. An installation still on v0.1.0, whose updates know nothing of environments, gets its `.venv`
  from the first pass of the runner after the update, and its console starts on it then — until that pass, the
  console says what it is missing. The console now starts in about 0.7 s instead of 0.3 s and holds about 58 MB instead of 34 MB.
- **A ticket's CI block fits on one line.** The list of checks is folded behind a chevron, leaving the state, the
  count of checks passed ("5/5") and the link to GitHub; a click or the keyboard opens it, and the choice is kept for
  every ticket. When the CI failed the list is open until you choose otherwise, and a folded line names the checks that
  failed.
- **The console's first load is lighter: 432 kB compressed in English, 484 kB in French, down from 486 kB for
  both.** The French dictionary is fetched only by a page that reads French, instead of by everybody, and what every
  page needs comes in 9 files instead of 19. The console's packages are up to date — Milkdown 7.22.3, Radix, Vite 8.3,
  TanStack Router — and `npm audit` no longer reports a high alert, only four low ones in the formula support Milkdown
  ships and the console does not load. React stays on 19.2: 19.3 mounts the palette and the conversation later, and a
  Ctrl+K pressed as the board appears went unheard. `PONOS_BUNDLE_STATS=1 npm run build` draws what each file of the
  bundle is made of.
- **Each installed version runs in a Python environment of its own.** `install.sh` and the automatic update make
  `~/.local/share/ponos/app-<commit>/.venv` before switching to the version, and the launcher runs it from there. The
  runner still needs nothing beyond the standard library, so nothing is downloaded; what changes is that the day a
  library is added, an update installs it there — and a version whose packages cannot be installed is never switched
  to, the one in use keeps running. An existing installation needs nothing: the update onto this version is made by
  the previous one, and the next pass creates the environment. A `python3` that cannot make one runs Ponos as before.
- **An update that adds a package goes through on Debian and Ubuntu without `python3-venv`.** Their `python3` cannot
  give an environment pip, so such an update would have been refused at every pass until somebody typed `sudo apt`.
  When the machine has neither `uv` nor `ensurepip`, `install.sh` and the update now fetch uv — the official binary,
  pinned, its SHA-256 checked — into `~/.local/share/ponos/uv`, without `sudo`, and install with it. Offline, the update
  is refused and the version in use carries on. An environment whose Python a distribution upgrade removed is made
  again on the next pass, and `ponos doctor` has an *Environment* section that says whether the `.venv` is there, runs,
  and imports every package it should — with `ponos update --environment` to make it again when it does not.
- **The repository has a `pyproject.toml`, a `uv.lock` and a lint.** `uv sync` installs the contributor's tools —
  pytest, pytest-cov, ruff — at locked versions; `uv run pytest` runs both suites (`python3 tests/run.py` still
  works without anything installed), and a new CI job runs ruff and pytest with coverage on every pull request.
  `docs/audit-technique-2026-10.md` is the technical audit that goes with it: what to change next, and in what order.

- **The Projects and Ideas lists filter the way the Dashboard does.** Their filters are buttons with their name in
  them, dashed until they ask for something and then saying what, instead of a row of labels taller than the fields
  under it. On a phone the bar wraps rather than scrolling sideways out of sight — "All types" and "Ticket" are no
  longer cut at the edge — and the Ideas filters other than the status fold behind a "Filters" button that counts
  the ones on. "Ponos, find me ideas" sits in the page's header, beside "New idea", with "Score the unscored ideas".
- **Ponos is orange, the Hermez one.** The robot, its favicon, the app icons and the Open Graph card were blue; they are
  the Hermez orange now, in both themes. The console's links, the running state, the unread dot and the recurrence summary
  take the brand's primary colour instead of the old blue, and the landing page's favicon is reloaded.
- **A ticket's priority is a score from 0 to 100.** Urgent, High, Normal and Low said little and tied often: the
  `Priority` column is now a number — 0, not important at all; 100, right now — and the ready tickets run highest
  first, the oldest first on a tie, an empty cell counting as 50. The console draws the score as a badge in a gradient,
  grey-blue towards 0, green at 25, yellow at 50, orange at 75, red at 100, on the cards, in the table and on a ticket's
  page; the board's columns are in that order too, and the search filters by score. A new ticket and a schedule are
  given theirs with a slider and a box, 50 when left empty, and anything outside 0–100 is refused, from the console as
  from the MCP `create_task` tool. `ponos init` creates the column as a number; a board still on the old select keeps
  its order — the words read as 100, 75, 50 and 25 — until its column is replaced. A repair ticket is born at 75, and a
  ticket at 75 or more is never run on the lightest model.

### Fixed

- **The bell lets go of a ticket that moved on.** A question answered, a pull request merged, a ticket the board now
  shows in another column kept its notification unread for good, and the count grew to 200 of them. Every board the
  console reads now settles them (`notifications.settle`): a notification whose ticket left the column it rang for —
  blocked or failed for a question, a red CI, a block or a failure, in review for a pull request — is read, once the
  board was edited after it or two minutes have passed. The 200 already there go the same way.
- **Ponos never merges a pull request with a red job, nor with one still running.** The check lived only on the forced
  road; a validated pull request was handed to `gh pr merge` unread, and a repository without branch protection took it
  — that is how #326 landed with its frontend job red. `merge_pull_request` now reads the checks first: a red job blocks
  the ticket (`merge.checks-failed`, the jobs named), a running one leaves it validated for the next pass. The README
  says how to protect `main` on a project; it is on for `hermez-agency/ponos` (`core (3.11)`, `core (3.13)`,
  `quality`, `frontend`, `image`).

- **The “Repair main” ticket is a Code / Bug ticket, and its pull request is merged on its own.** It was born without a
  type, so it was classified like any ticket and its green pull request waited in *In review* while every other pull
  request waited behind it. It is now created as *Code*, sub-type *Bug*, priority 75, and the pull request it opens is
  validated without you — merged once its CI is green, whatever *Force validated* says — after which the pull requests
  set aside for the red base are replayed as before.

- **An OpenRouter model in the console answers again.** Claude Code adds `/v1/messages` to the address it is given, and
  it was given `…/api/v1`: the request went to `/api/v1/v1/messages`, a 404 it reported as "issue with the selected
  model". Sessions now get the address without its `/v1` (`https://openrouter.ai/api`); transcription, the model
  catalogue and `OPENROUTER_BASE_URL` keep `/api/v1`.
- **The installed app's icon is no longer on a black square.** The console's icons were opaque PNGs on the console's
  dark grey, so Chrome's install dialog, the launcher and the taskbar drew the robot on a black square. The icons a
  system draws as they are now are the robot alone on a transparent square, with a margin. The maskable icon (cropped
  to a circle or a squircle) and the iPhone's (which fills transparency with black) keep a ground, now the brand's warm
  cream rather than the console's grey, and the manifest's colours say the same.
- **A card is dragged to another column again.** Since the move to react-resource-view 1.0, the board declared its
  tickets not updatable, and the package only lets a card be picked up, and writes its drop, where a record may be
  updated: no card moved. Each column also only knew its own cards, so a card dropped in another drawn column was
  ignored. A card now moves wherever it is picked up — its title, its foot, its body — and the ticket changes status in
  Notion through the outbox, as the "Move" menu does, put back in its column when the write is refused.

### Added

- **One command, then the browser.** The installer checks the machine first and says everything missing at once,
  each with the command that installs it here (`apt-get`, `dnf`, `pacman` or `brew`); it finds a recent enough
  Python under its versioned name, offers to install Claude Code, checks its sign-in and the free disk. It no longer
  asks for a Notion token in the terminal: it starts the console and opens it. A machine with `systemctl` but no
  user session — WSL, a container, SSH — no longer stops the script on `Failed to connect to bus`: the console is
  started in the background instead, and a Mac gets two launchd agents.
- **The first connection goes all the way to a ticket played.** It opens on the language, and gains a first
  project — a repository found on this machine, a GitHub one, or none — and a demonstration ticket created and run
  on the spot, followed until its answer is on the board. The Notion step is three gestures with a picture of
  Notion's *Connections* menu: the token is checked against Notion before it is written, and the page shared with
  the integration appears on its own, one click from having the board built under it.
- **`ponos doctor` from the console.** The summary — at the end of the first connection and atop the settings —
  gains a line for the machine itself (git, Claude Code, its sign-in, the disk, with the command that fixes each),
  and *Run the full diagnosis* shows `doctor`'s text with a button that copies it for support. `doctor` itself now
  prints the install command beside a missing tool.
- **GitHub reached with an access token, no App needed.** Settings › GitHub (and the first connection's GitHub
  step) takes a fine-grained personal access token next to the GitHub App: the console links to the token form with
  the permissions already filled in, checks what is pasted — who it is, which repositories it reaches, whether
  Contents and Pull requests are on read and write — and says exactly which permission is missing before keeping
  anything. The token goes to `secrets.env` (0600), comes from `PONOS_GITHUB_TOKEN` in a container or Dokploy, or
  from a vault item (`[github_access] token_item = "pass:ponos/github"`); it is masked wherever the runner writes and
  never sits in `config.toml`. Clone, push, pull request and comments go through the same door as the App's, and
  `[github_access] mode` puts the App or the token first. `ponos doctor` checks the token too.

- **A project's type, description and site are corrected from the console.** The "Edit the project" drawer has them
  under "The project", as the "New project" window asks for them: a project switched to Writing loses its repository
  and folder, one switched to Code needs one of the two, and a site that is not an `http(s)://` address is refused. The
  page's header says the project's short id, `#0000cafe`, with a button that copies the whole one — as a ticket's does —
  and on a phone its "…" menu stays on the line of the edit button.
- **The console on your phone, and Claude's connector, over Tailscale.** `ponos tailscale enable` installs a user unit
  that waits for the tailnet, then serves the console on `https://<machine>.<tailnet>.ts.net:8443` (tailnet only) and
  publishes through Funnel on 443 the three paths the MCP connector needs — `/mcp`, `/oauth`, `/.well-known` — and
  nothing else. A closed lid, another network or an expired login are waited out, and a configuration `tailscaled` lost
  is put back; `status`, `apply`, `watch` and `disable` (which takes both doors down) complete it. The console also
  answers 404 to any other path on a request that carries Funnel's header. Never enabled by the installer or an
  update; README: "From your phone".

- **A prompt on every change of status: the `On` column.** Write a prompt in a ticket's new `On` column and Ponos runs
  it, in a session of its own, each time the ticket's status changes — yours or the runner's — told the old status, the
  new one and the ticket (title, project, pull request, last report). One prompt for every transition, so « if it goes to
  validated, create the deployment ticket » is one line on the ticket. One execution per change, never twice after a
  restart; what an execution moves or creates never wakes a prompt in turn, and a chain of tickets made by prompts stops
  at `runner.on_max_depth` generations; each execution is capped by `budget.on_usd` (1 $) and `on_timeout_minutes`; an
  error is a comment on the ticket and never touches its status. The console shows and edits the prompt on the ticket's
  page, with the list of its executions (transition, state, cost, result). `ponos init` adds the column; a Markdown
  board reads it as an `On:` field.
- **The disk is looked after.** A worktree is removed once its ticket has been done *or cancelled* for the retention,
  and any worktree untouched for `stale_worktree_days` (30) goes whatever its ticket — never one whose ticket is in
  progress, nor one holding uncommitted changes or commits no remote has; its local branch goes when a remote holds all
  of it. Under `min_free_disk_mb` (5 GB) free, a tidy runs before a ticket starts, and if the space is still short the
  ticket stays in Ready (not Blocked) with a notification and an alert in the console. `worktree_exclude` makes new
  worktrees without big folders such as `docs/media` (sparse checkout). Settings › General now shows the free space
  and the heaviest worktrees.
- **A vault for the keys a ticket needs.** A ticket that publishes a package or redeploys a service no longer needs its
  token written in the ticket: `[vault]` in `config.toml` says where keys are read — the GNOME keyring (`secret-tool`),
  `pass`, the Bitwarden CLI or the environment and `secrets.env` — and which ones each project is given, by its Notion
  name. They reach that project's sessions, and no other's, as environment variables; the prompt names them and never
  holds them. Any value read is replaced by `***` in the comments and pages written to Notion or the Markdown board,
  the session transcripts, the runner's log, Telegram and Slack, and the console. `ponos doctor` reads each key and
  says whether it is there, without printing it.
- **The Projects page in two columns.** The list of projects is on the left — one compact line each: icon, name, type,
  tickets and last activity — under the search, the *Type* filter and *New project*; on the right, the global context
  stays folded to a few lines (*See all*, *Edit*, its character count) and, under it, the project picked in the list shows
  its repository, its folder, its brief, *+ Ticket* and its “…” menu. A project just created is picked straight away. On a
  phone the list comes first and a project picked opens full screen. *Cards* and *table* are still a tab away.
- **Create a project from the console.** *New project* — beside *cards / table* on the Projects page, and in Ctrl+K —
  opens the same kind of window as *New idea*: name, description, *Code* or *Writing*, the repository on GitHub or as a
  folder of this machine (whose `origin` fills GitHub in), the public site and the brief, which becomes the page's
  body. The console says whether the repository is already cloned here or will be at the first ticket; a name already
  taken, an address that is not GitHub's or a folder that is not a git repository are refused under their field. The
  new card comes first in the list, marked, with its *+ Ticket* ready — or *Create a first ticket* opens the ticket's
  form with the project already chosen. Works the same on a Markdown board.
- **Connect GitHub in one click.** Settings › GitHub (and the GitHub step of the first connection) creates a GitHub
  App from a manifest — on your account or an organisation's — then leads to the choice of its repositories and back
  to the console, which says « GitHub connected » and lists what the app reaches. Code tickets on those repositories
  then clone, push and open their pull requests as `{app}[bot]` with an installation token renewed on its own, even
  during a session of more than an hour — no `gh auth login` on the machine. The app's credentials join the other
  secrets in `secrets.env`; *Disconnect* deletes them. Without an app, `gh` works as before; `ponos doctor` reports the
  connection.
- **A « Sessions » entry in the menu: the history of the conversations with the workspace, and a choice of model per
  conversation.** The chat is no longer one conversation that « new conversation » buries: each is kept in `ponos.db`
  (the former `chat.json` becomes the first of the list) with a title made of its first message — renamable — the date
  of its last message, its model and, if you give it one, its project. A row reopens the conversation with its whole
  transcript and resumes the same Claude Code session; the search looks in the titles and in what was said; deleting
  asks for a box to be ticked, as for a project. A picker in the bar over the conversation changes the model, kept per
  session: `opus`, `sonnet`, `haiku` and `fable`, and — with an OpenRouter key — any model of OpenRouter's catalogue,
  searched by name, the latest used first (without a key, only Claude's, with a link to the setting). A session on an
  OpenRouter model goes through OpenRouter whatever `claude.provider` says. `web.chat_model` sets the model a new session
  starts on.
- **A schedule can be run now: a ▶ « Lancer maintenant » button on each row of the table and in the
  header of an opened schedule.** The runner writes the ticket into the ready column exactly as it
  would at the due moment, a toast says « Ticket créé » with a link to it, and `Last` is updated —
  `Next` is not touched, so the planned occurrence still happens. It works on a paused schedule too,
  without turning it on, and the button spins while it runs so a double click makes one ticket. A
  failure is shown in the toast.
- A ticket says how long Ponos worked on it. The Brief has a « Time » cell next
  to « Spent » — 12 min 30 s, 1 h 05 — that counts live while a session works,
  shows ⏸ and the reason when the ticket waits on your answer, is blocked or
  waits for credit, and opens on the working time, the time on hold and the
  number of sessions. Review and the wait in Ready are not counted. The card
  wears it beside the cost (12 min · $0.64). It is read from the runs the
  journal already keeps, so it survives a restart, and tickets from before it
  have theirs; a ticket with no run says « — » rather than a wrong figure.
- **The dashboard's statistics say whether a project moves on or mends what it broke.** The two
  charts *Created and closed* and *Open tickets* are one, *Activity*: the tickets created and
  closed as bars a day, the open ones as a line over them, the three figures of a day under the
  pointer. A *Validated* ticket now counts as closed, so the open ones are every card but *Done*,
  *Validated* and *Cancelled*. Beside it, the tickets created by type and sub-type, day by day or
  week by week, filtered by type and by project, with a *Unclassified* part for the ones with no
  sub-type yet, and the **regression rate** — bugs over bugs, features and improvements — with its
  trend against the period before and, over every project, a table of the ones that break the most.

- **A code ticket says what kind of change it is: Bug, Feature, Amélioration, Chore, Refactor,
  Perf, Docs or Sécurité.** A `Sous-type` select on the board (`ponos init` adds it, `ponos doctor`
  asks for it), ignored on the other types. Empty, the runner fills it before the ticket runs: from
  the title's prefix (`[Bug]`, `[Feature]`, `[Ops]` for a Chore…) without asking anybody, otherwise in
  the same light session that tells the type — an *Amélioration* when in doubt, said in the report,
  never a block. A value already there is never rewritten. The session is told the prefix of its
  commit (`fix:`, `feat:`, `chore:`…) and the CHANGELOG section it writes under, and a Bug is asked
  for a test that reproduces it before the fix; the pull request takes the same prefix in place of
  the title's tag. `ponos subtypes --backfill` fills the code tickets already on the board from their
  prefix alone — the done ones only with `--all`, since an edit moves their closing date; the console
  reads the prefix of a code ticket whose column is empty, so they are counted anyway. The console shows a badge of it on the card (an icon and a colour each), filters the
  board by it, offers it in *New ticket*, and counts the code tickets done by sub-type and by week,
  with the average cost and duration of each. The automatic model choice reads it too: Docs and
  Chore start one level lower, Sécurité one level higher (`runner.auto_model_subtype_*`, in the
  Settings' model table), never past the four levels.
- **Every idea has a relevance score, from 0 to 100, in colour.** A circle at the top of each card —
  in the list, the table, the pile and the idea's page — says its number in green (70 and up),
  orange (40 to 69) or red (under 40), and why in its tooltip; *Not scored* is grey. Ponos scores the
  ideas it proposes by a grid written in the prompt (impact 40, fit with the brief 25, effort against
  gain 20, originality 15); an idea written by hand is scored behind the form by the light model
  (`runner.classify_model`), and says *…* until it is. *Score the unscored ideas*, on the *Ideas*
  page, scores the ones from before, after saying how many and the most it may cost. The lists sort
  *Most relevant first* — the new ideas do by default — and filter by colour. The score is in
  `ponos.db` (migration `ideas_have_a_score`) and in what `list_ideas` answers over MCP.

- **A bell in the console's header for what asks for your attention.** A small badge counts what you
  have not seen; a click opens a dropdown over the board — newest first, an icon for the kind, the
  ticket's title, its project, how long ago — and a click on one opens that ticket's card and marks it
  read. *Mark all as read* empties the badge. It rings when a session stops on a question (the one
  that matters), a pull request is ready to read, the checks of a pull request fail, a session fails,
  or a ticket is blocked — never for a ticket taken or moved to progress. Notifications are written by
  the run into `ponos.db` (migration `notifications`), arrive on the stream like the board, so opening
  the panel asks for nothing, and read ones are forgotten after thirty days. System (push)
  notifications and a "CI is green again" ring are not part of it.
- **The console installs as an app.** Chrome, Edge and Android offer it from a small icon in the bar
  (*Install the app*); on iOS the same icon says *Share → Add to Home Screen*. It opens in a window
  of its own on the board, with the robot as its icon. A service worker keeps the console's files
  for a quick start — never the tickets, which come from the server every time — and shows a page
  that says so when the server cannot be reached. A new version is noticed by the installed app,
  which asks *New version available — Reload*. Browsers only install over HTTPS or on `localhost`.
- **A ticket in review shows whether its CI passes.** A badge on the card — running, passed or failed
  — and, in the ticket's window, the list of its checks with a link to GitHub's page for them. A
  pull request without a single check shows nothing, never a green. The runner reads the checks of
  the pull requests in review a pass at a time (every 30 seconds while one runs, every five minutes
  once settled) and keeps them in `ponos.db`, so the board stays as fast as it was; a push puts the
  state back to running, and a ticket that leaves review is no longer followed. The state is also
  written to a new `CI` select (`en cours`, `réussi`, `erreur`) that `ponos init` adds to the
  tickets board, for a Notion view to filter on.
- **The ideas list reads at a glance, and its filters live in the address.** Each card puts its title
  first, its status and type as badges, a few lines of description and who wrote it, small — and one
  button in plain sight: *Turn into a ticket*, or *Open the ticket* once it is one. Keeping, throwing
  away and making new again moved to the card's *…* menu, rewording to its pencil, and the title
  opens the whole idea beside the list. The status, project and author filters are the same, now in
  the address (`filter=…`), so a link or a reload opens the same list; *New idea* is at the top of
  the list and on an empty one, and a table sits beside the cards.
- **The projects list can be searched by name and narrowed to a type.** A search field and a *Type*
  menu (code or document) sit above the cards and the table; the words match a project's name or
  its type, whatever the case and the accents. Both live in the address (`filter=…`), so a link or
  a reload opens the same list, and when nothing matches the list says so with a button that clears
  the search.
- **A *Cancelled* status, for the tickets you give up on.** Terminal like *Done*, and apart
  from it: the runner never runs a cancelled ticket — not from *Ready*, not woken by a comment,
  not named with `ponos run --ticket` — and the statistics count it neither closed nor open,
  while what it already cost stays in the spending. In the console it is the last column of
  the board, with a hollow grey dot, cards struck through, its place in the status filter and
  in the breakdown by status; any card but a running one offers **cancel the ticket** behind
  its "…", a cancelled one **reopen** (back to the drafts), and *Abandon* or *Reject* in the
  decision panel file the ticket there. The Markdown board knows it out of the box; on Notion,
  `ponos init` adds the option to a select, and `ponos doctor` says when the board has none —
  the gesture is then simply not offered. `cancelled = "Cancelled"` names it under
  `[notion.status]`.

- **An *MCP* tab in the console's Settings explains MCP and plugs Ponos in step by step.** It says
  in a few sentences what an MCP is (the Notion one a session reads its ticket with, Ponos's own
  that Claude talks to), then walks through it: pick Claude Code, Claude desktop or another client,
  copy the command or the JSON block already filled in with this console's address (local or
  public), and press *Test the connection* — it asks `/mcp` what a client would ask first, and a
  failure names its probable cause and what to do (no public address, certificate, a proxy that
  rewrites the path or the host, an address the console does not recognise as its own). Below,
  the MCP servers Claude Code holds for the sessions, each with *connected*, *to sign in* or
  *failing*, and how to add one. No key is ever shown: `ponos mcp token` stays a terminal command.

- **A pull request red by its own fault is repaired by a session before it is blocked.** When
  the checks of a validated pull request are still red after the failed jobs were run again,
  and are not red on its base, a session is sent after them on the pull request's branch:
  it is given the names of the red checks and the end of the log of their failed jobs, fixes
  what the branch broke (not the base, no test turned off) and commits. The runner pushes the
  fix and waits for the CI: green, the merge goes on; red again, or a session that answers
  *blocked* or commits nothing, the ticket is blocked as before (`merge.checks-failed`) with
  the session's report. One attempt per ticket and per head commit, kept in `ponos.db`.
- **A red base is no longer a red pull request.** When the checks of a pull request fail on
  the newest commit of its base too, the ticket is no longer blocked (or, until now, merged
  over a red base): it is set aside in *Validated* with a line on its card — “the base is red,
  it is not this pull request” — and no new session. One ticket “Repair `<base>` of
  `<project>`” is opened, *Ready*, *High* priority, with the failing jobs and the link of the
  run, and only one while it is open. Each pass reads the base again, and the pull requests
  set aside go on by themselves once it is green. `ponos doctor` and `ponos projects` warn
  about a base with no CI run at push, or only skipped ones.
- **What a session may do alone is written down.** A `[permissions]` policy — `allowed` and
  `ask`, edited on the Execution page of the Settings with sensible defaults — is read by every
  session: redeploying a service, tagging a release or merging a validated pull request no
  longer raise a question, publishing on a public registry or sending a message to anybody but
  you always do. A session that needs a `sudo` password, an `npm login` or a code received by
  e-mail stops asking yes or no: it prepares the commands, ends blocked with `access.sudo` or
  `access.credentials`, and the ticket carries on when you answer « fait ». A ticket aimed at
  another of your repositories gets it cloned and its project created, when `allowed` says so.
- **Fewer merges blocked by the queue itself.** Conflicts in generated files and in
  `CHANGELOG.md` no longer cost a session: a replay keeps both sides of the changelog, takes the
  base's version of the files a project declares generated (`generated = [...]` and `build = "..."`
  in a `.ponos.toml` at the root of its repository), runs the build and commits its result in the
  replay — a session starts only for a conflict in hand-written code. The merges of one repository
  now wait in a line, one at a time, each pull request replayed on the base the previous merge left,
  and `runner.max_concurrent_per_project` (default 2, also in *Settings*) keeps one project from
  taking every place with pull requests that touch the same files.
- **A search over the board, and over a project's tickets.** A bar over the columns finds a
  ticket by the words of its title, of its result, of its pull request, by its short id, or by
  a pasted branch or Notion address — case and accents set aside — and filters that combine:
  type, status, priority, model, project, period, and a few switches (a pull request, waiting
  for credits, not yet synchronised, what it cost). The columns stay where they are and say how
  many cards they kept (`3 / 12`), the words found are marked on the cards, and the search lives
  in the address: a link to send, a reload that keeps it, and the table under the same search.
  **/** goes to the field, **Escape** empties it; on a phone, the filters fold behind one button.
- **A runner that survives its own bad days.** A worktree left in the middle of a rebase, a merge
  or a detached HEAD with changes (a session killed while it resolved conflicts) is saved to a
  local branch `ponos/backup/<id>-<date>`, the operation is given up, and the ticket starts again
  from its own branch — the session's prompt and the ticket say where the backup is, instead of
  "I could not make the worktree". A session killed from outside (SIGKILL/SIGTERM, or cut by a
  network outage) is resumed once after `runner.relaunch_delay_seconds`, if the network answers;
  killed again, the ticket is blocked as `session.killed` with the exact cause (the signal, the
  kernel's out-of-memory line, the network). When Notion cannot be reached (DNS, connection) the
  run ends quietly instead of failing every few seconds, and no ticket is marked failed. No
  session is started while less than `runner.min_free_memory_mb` (2048) is available; `ponos
  doctor` reports it.

- **Unblock and Decide, on the cards that wait on you.** A blocked card opens a panel that says
  why it stopped — in one sentence, under its kind: a decision to make, missing access,
  something to do by hand, credits, failing checks, a conflict, too big for one ticket — what is
  done, what is missing, and the choices that would get it moving: the session's own options,
  answer the question, it's done run it again, another model, an instruction, split into draft
  sub-tickets, abandon, or an instruction of your own. A card in review opens one with what it
  delivered, its pull request and checks, the points the session could not check, and validate,
  send back (ready-made for red checks, tests, screenshots, a rebase) or reject. Each choice
  leaves one comment the next session reads, and moves the ticket. A popover on a desktop, a
  sheet from the bottom on a phone; and `list_solutions` / `apply_solution` in the MCP connector.
  Sessions now name what they stopped on (`CATEGORY:`) and what to check (`CAVEAT:`); tickets
  blocked before that are read off their words.

- **Why a ticket stopped, as a cause you can count.** Every block or failure now carries a
  code from a catalogue (`merge.checks-failed`, `session.question`, `worktree.residue`…), with
  its family, who has to move, a label and a line of help in French and English, the gesture it
  proposes and what the runner may do about it alone. The card of a stopped ticket shows a badge
  with the family's icon, the help under it and the gesture — *answer*, *run again*, the pull
  request; the board's search filters by cause; the statistics show the blocks by cause and by
  week. The code is kept in the history and the runs (`ponos.db` migration 18, which read every
  past stop back from its sentence, French or English, and files what matched nothing as
  `unknown`), and written into a new **`Blocage`** select of the Notion board — run
  `ponos init` to add it; `ponos doctor` says when it is missing.

### Changed

- **The settings say which language of the console wins.** The two settings that were both called the console's
  language sit together and say whose they are: "in this browser", which comes first, and "by default for all", for
  every browser that has not picked one. The page is titled "Configure the runner", the breadcrumb names the page open
  ("Settings › General") rather than `config.toml`, and the cards take the column's width, the sentence under each
  field wrapping instead of being cut short.
- **The list of schedules says each rule in a sentence, and is searched like the projects.** One "Rule" column —
  "Every hour at :00", "Every Monday at 09:00" — replaces Cadence, At and Day, which had an hourly schedule run "at
  00:00" on an empty day. A schedule nothing has made yet has an empty "Last", not a dash in a badge, and a date stays
  on one line. On a phone each schedule is a card with its rule, its dates, its project and its problem, the switch and
  the run button beside its name, instead of a table cut after "Next". A search over the names, projects and rules, a
  project and on / paused filters sit over the list, in the address. The switch now writes only the tick: it used to
  send the row's other cells too, and emptied the model, the priority and the type a schedule had been given.

- **The token page looks like the console it opens.** The page that asks for the console's token (and the sign-in and
  MCP consent pages beside it) is drawn in the console's stone and orange, its card, field and button, dark unless the
  console was switched to light in this browser. It now says the token is kept as `PONOS_WEB_TOKEN` in `secrets.env` (or
  the environment) rather than in `web.token` of `config.toml`, and says so when the token a browser kept is refused —
  usually another console on the same address, a test one beside 8787, whose cookie replaced this one's.

- **A tidier console, after a page-by-page review.** The Projects page puts its projects first: the search and the
  *Type* filter are one compact row (*All types* rather than *Choose…*), the three layouts have three icons, the count of
  projects with a repository and the folder repositories are looked for are one line of small print under the list —
  said in words, not as `runner.workspace_root` — and in the cards and table layouts the global context is under the
  projects, its empty state one line and a button. *Edit the project* is in three groups (*The project*, *Where its code
  is*, *The brief*), in the words *New project* uses (*Name*, *GitHub*, *Local folder*), and refuses a repository that
  is neither `owner/repo` nor a clone URL before it is sent. *New project* says what each type means, what the site is
  for, that the brief can wait, and why its button is greyed. The board's columns, a ticket's type and its priority are
  said in the console's language everywhere — *Prêt*, *En cours*, *Rédaction*, *Urgente* — where a French console mixed
  them with English; a schedule set to every hour says that only the minutes count. Ideas and Schedules use the whole
  width, as the board and the projects do, and the Ideas filters are no longer cut at the edge. On a phone, the
  dashboard no longer scrolls sideways.

- **The image moves to `ghcr.io/hermez-agency/ponos`.** The repository now lives under the hermez-agency organisation,
  and the next release publishes its image there: `docker-compose.yml`, the Dokploy template and `release.py bump`
  point at it. The old `ghcr.io/salvadorcardona/ponos` (`0.1.0` and `latest`) stays where it is, so an existing
  installation keeps pulling it; change the `image:` line to follow the new releases.

- **The Projects page uses the whole width of the screen.** The centred column and its wide empty margins are gone, in
  the split, cards and table layouts alike: the list keeps its width, the context and the project picked take the
  rest, and the cards show up to five per row on a large screen. A phone is unchanged.

- **The New ticket window no longer says what the ticket will come back as.** The « Ce que ça donnera » card at the
  foot of its settings column is gone, whatever the type; the type and the project are still chosen the same way.

- **Sub-types are told apart by their colour, without emojis.** 🐞, ✨, ⬆️ and the others are gone from the console:
  on a card's badge, in the sub-type filter, in the forms, in the model settings and in the statistics, a sub-type is
  a coloured dot and its name — red for Bug, green for Feature, blue for Improvement, grey for Chore, violet for
  Refactor, amber for Perf, brown for Docs, orange for Security, dark grey for *Unclassified*. The dots of a legend
  are the colours of its bars, in the light theme as in the dark one. `ponos subtypes` in a terminal keeps its icons.
- **The chat shows the steps as a timeline of cards, in plain words.** No more *Show / Hide the steps* toggle: each step
  of a turn is a card, drawn as it happens (spinner, then done or failed), closed until opened, with *Expand all* /
  *Collapse all* above them. A card is titled « I check that everything works », « I look at the scheduled tasks »,
  « I read the project's code » — in the console's language, never a shell command or a tool's name (« I work on the
  project » when nothing fits), and so is the line under Ponos while it works; the command, the tool and its answer are
  in the card's body.

- **The console and the landing page wear Hermez's design system (the Portfolio theme).** Warm stone greys, the
  brand's orange for the buttons and the focus ring, headings in a very bold Bricolage Grotesque — bundled with the
  console, no font service — and the system's own face for the text; the radii are derived from one `--radius`. The
  console still opens dark, on the same stone. The status colours keep their meaning, a shade deeper in light where
  they fell under 4.5:1, and the few texts written white on a light colour in dark are now dark.
- **Desktop notifications are two short, clean lines.** The title is the verdict and the ticket, without the project
  it opens on, cut on a word around 60 characters; the body says the project and where the work is (PR #, commits,
  « answer in the page »), then the summary cut around 120 characters — no address, no price, no duration, no
  Markdown. A pull request gets a « See the PR » button beside « Open the ticket », the icon is Ponos's, and only a
  question stays on screen (« Question », « Answer in the ticket »): a failure goes away like any notification, with
  the warning icon. Notion comments and Telegram or Slack messages are unchanged.
- **A blocked ticket is answered in its discussion: the Unblock tab is gone.** The question the session stopped on is
  said once, as a bubble from Ponos — what is done, why it stops, the question in bold — with quick replies under it:
  *Yes* / *No*, one per option of a choice (in full, wrapped, never cut), *Yes, close it* when the session proposes to
  close the ticket — a duplicate, nothing to do — which files it as done with a comment, and *Run it again as it is*. A
  click answers and runs it again, as the same words typed would. One field takes the answer or an instruction, with
  the model beside it; *Run it again as it is*, *Abandon* (confirmed) and *See the session* are behind ⋯. A blocked
  ticket opens on its discussion, marked, and an old `&tab=unblock` link lands there.
- **Ponos is shown at work after you write.** From the moment a message or a quick reply is sent, the discussion shows
  the robot and *Ponos is working…* under it, until Ponos answers — or the session fails, which is said in its place.
- **The run's technical lines are discreet.** *Model chosen automatically — opus …* and the like are a small grey line
  across the discussion rather than a bubble each, and a session that committed nothing is said on the session's line
  instead of a red badge over the ticket.
- **A card in review offers one thing to do: Decide.** A pink button across the card's width, and beside
  it a « ⋯ » that holds the rest, in the order you reach for it — *Validate and publish*, *Run the agent
  again*, *Mark done* and, apart and in red, *Cancel the ticket*. Five buttons in three styles made Decide
  and validate fight for the eye. Each gesture asks what it asked before and moves the ticket where it did;
  the state of the CI moves to the line along the bottom, beside the age and the cost, red when it fails.

### Fixed

- **A desktop notification shows the orange Ponos, and the site has the icons a browser asks for.** The dock and
  notification icons had stayed on the old blue robot when the mascot went orange; `scripts/mascot.mjs` now draws them
  with the rest. the-ponos.app answers `/favicon.ico` and `/apple-touch-icon.png` instead of a 404, and an address it
  does not have lands on a page of its own rather than GitHub Pages' generic one. The repository's homepage is
  https://the-ponos.app, and `config.example.toml` lists hermez-agency beside SalvadorCardona as the code does.
- **The dashboard's "Created, by type and sub-type" counts what the Created card counts.** It opened filtered on Code,
  so a ticket with no type, or of another type, was left out and the card said no ticket was created while the
  Created card and "Created, by project" counted it. It now opens on all types, the type menu has a "No type" entry,
  and a type with no ticket says which one it is: "No Code ticket created in the period."
- **The Markdown fields of the console's forms start their text where the other fields do.** The brief of a new
  project or of the project's drawer, a new ticket's and what a schedule does each time began forty pixels to the
  right, in the gutter Crepe keeps for its block handle. In a form the text now starts at the same 12px as the title
  beside it and the handle is not drawn — `/` still opens the blocks; the full-page editors, the global context and a
  project's brief, keep their gutter and their handle.
- **A ticket without a repository no longer fails with “the runner itself broke” when its session met Claude in Chrome's
  refusal.** A browser-internal tab refused by Claude in Chrome leaves an event in the session's log whose message is a
  sentence; looking for the pull requests the session opened tripped on it (`AttributeError: 'str' object has no
  attribute 'get'`), after the work was done and before its answer reached the page. It is skipped now.

- **`main` is green again: the console's first load is back under 500 kB.** The two-column Projects page took it to
  501 kB gzipped and the core suite failed on every push. The project panel and a ticket's *Discussion* tab are now
  loaded when they are opened, which brings the first load to 491 kB.
- **Desktop notifications say what happened, where, and what to do.** The title is the event and the project (*Ponos a
  une question — Leadz*, *Ticket terminé — Adam*, *Ticket en erreur — Portfolio*), the body the ticket's name, cut on a
  word, and one sentence — never a bare « Ponos ». A ticket's later notification replaces its earlier one instead of
  stacking, and the test suite no longer posts notifications of its own on the desktop of whoever runs it (the
  « Question · t » that read « Answer in the ticket » in English).
- **The Ponos icon has no black square in notifications and the dock.** The mascot, cut out on a transparent
  background in 48, 64, 128 and 256 px, replaces the console's opaque square, and `install.sh` puts it in the icon
  theme.
- **A schedule says what its tickets are.** The Schedules database gets `Type` and `Sous-type` columns — the tickets'
  own options, added by `ponos init` and set in the schedule's window in the console — and each ticket is born with
  them, beside the project, the model and the priority. A ticket born typed is never classified: a long, well-written
  brief no longer turns a code schedule's tickets into *Writing* ones that end in *Done*.
- **A pull request opened by a session that was not on the code road is no longer lost.** When a *Writing* (or any
  non-code) session runs `gh pr create` itself, Ponos attaches the pull request to the ticket's `Pull Request` column
  and sends the ticket to review rather than done, saying so in its report — so validating it merges it, as any other.
- **`~/.local/state/ticket-runner` stops coming back in the journal.** An old directory holding nothing but empty
  folders and a console token — what an old checkout's test suite recreates — is tidied once, without a word, instead
  of « was left in place » on every command and every ten seconds.

- **An automatic validation the CI stops says which CI, and why.** With Validation automatique on for
  Code tickets, a pull request whose checks were red stayed in review with « ses vérifications échouent »
  and nothing more — on every pull request of a private repository whose GitHub Actions jobs were refused
  for the account's billing, as on one whose tests really failed. With the `gh` Ubuntu ships (2.46), which
  has no `gh pr checks --json`, the runner could not even read which checks were red: no names, no second
  run, no comparison with the base, nothing in the console's panel. It now reads them from the pull request
  itself, and the card says « CI : rouge sur `Tests`, là où `main` ne l'est pas » — or « CI : pas démarrée —
  GitHub dit : The job was not started because… », which is the account to look at, not the code. A job
  GitHub refused to start is not run again either: it would be refused the same way.
- **The Calendar view of the schedules shows every launch, not just the next one.** It drew one event
  per schedule, on the day of its `Next` — a daily schedule was one dot, an hourly one too, and
  nothing said what had already happened. It now lays out the runner's own rule forward from the very
  `Next` the list shows, in the runner's timezone (nine o'clock stays nine on either side of the
  change to winter time): a daily schedule is there every day, an hourly one is folded into a single
  « 24 lancements » event a day, a schedule that is off has no launch to come, and `Last` is drawn
  greyed as the launch that has happened. The week and the day show the whole of it, from 00:00 to
  23:00 instead of 07:00 to 21:00, and an event's window says what it is and leads to the schedule.

- **Ideas are scored again, and a scoring that fails says why.** A scoring call was stopped at 0.10 dollars
  while it costs 0.12 to 0.14, so no idea was ever scored and nothing said so. The ceiling is now 0.50 dollars
  a call, the prompt carries less (a shorter brief, fewer tickets and ideas to compare with), and a call whose
  estimate would go over the ceiling is not started. When one fails — budget, credits, unreadable answer —
  the cause is kept on the idea ("Not scored — try again", the cause in its tooltip), written to the
  console's journal, and toasted when *Score the unscored ideas* was the one that failed.

- **A ticket opens and closes in a blink on a full board.** On a board of 446 tickets, opening a card
  took about 400 ms and closing it 550 ms, because the whole board was drawn again each time — the
  open ticket was held by a component every card sat under — and because the window, by setting
  `pointer-events` on the page, made the browser compute the style of every card again. Now only the
  window is drawn, and the cards scrolled out of view are skipped by the browser: opening takes about
  80 ms and closing starts at once (the rest is the window fading out). The board no longer waits
  on a redraw to show its first tickets, either.
- **A branch's code can no longer break `ponos.db` for main.** The local database remembers
  each migration by its name, not only how many it went through: a file migrated by a branch
  whose migrations were in another order is finished by main without applying one twice —
  where it used to stop every run's journal on « table write_ups already exists ». A file
  that went through a migration this Ponos does not know is refused untouched, and
  `ponos doctor` warns when the migrations are not in the code's order. Ponos launched from a
  checkout (`PYTHONPATH=src`) no longer writes the real state unless `XDG_STATE_HOME` is set.
- **A ticket whose work was not a commit is no longer blocked for want of one.** An audit, a
  check, a deployment or a setting in production is classified as *Writing* or *External
  action*, and a classification that hesitates between *Code* and another type takes the other
  one instead of asking — and says so in its comment. A code ticket that committed nothing,
  changed nothing, and reports work done outside the repository (Dokploy, DNS, Notion…) is
  *Done* with its report in the page; one that changed code without committing it is still
  blocked.
- **A session that stops without its report is asked for it before the ticket is blocked.** No
  `ANSWER.md`, or on a code ticket no commit and no `RESULT` line: the same conversation is
  picked back up once, told to write the account of what it did and nothing more. A ticket is
  never picked up this way twice.
- **A question answered is no longer a reason to block again.** A session that answers what you
  asked in a comment and has finished is told to end `RESULT: ok`; one that says `blocked`
  without asking anything, its deliverable written, goes to review.

### Security

- **A password or a token typed in an answer no longer stays in the ticket's comments.** The console holds back a
  message that looks like one — a value after « mot de passe : », `password=` or « token est », a GitHub, npm,
  Anthropic, OpenRouter or Slack token, a private key, a password inside an address — and says so; sent again, it
  goes, masked. Whatever the runner recognises is replaced by `••••••` before it is written to Notion, shown in the console
  or relayed from Telegram and Slack: the label stays, so the next session knows something was given, never what.

### Changed

- **A new idea is written in a quick-entry window rather than a drawer the height of the screen.** « New idea »
  opens a window as tall as what it holds — a sheet up from the bottom on a phone, its button the whole width. Its
  header is whom the idea is for, a menu of the workspace and its projects (the page's own already picked) ending on
  « Propose a new project », which makes the idea a project-creation ticket and replaces the old Type select. The
  title is the largest thing in it and has the cursor; the category is four chips, pressed again to let go, and the
  sentence about Tech only shows once Tech is chosen. « Create the idea » stays greyed until there is a title,
  Ctrl+Enter (⌘+Enter) sends it from any field, and « Create another » empties the window for the next one instead
  of closing it. Same fields sent, nothing changed on the server. Screenshots in `.github/screenshots/idea-window/`.
- **A schedule is written in a window in the middle of the list, as a few clicks rather than seven fields.** « New
  schedule » no longer opens a drawer against the edge: a 620px window titled « New recurring ticket » — and « Edit the
  schedule » for one opened from the list, the same window — closed by Escape, its cross or a click beside it, the
  whole screen on a phone. The cadence is four buttons (every hour, day, week or month), the day only shows when it
  matters and in the shape it takes — seven round pills for a week, « On the [1] of the month » for a month — and the
  hour is a real time field, 09:00 by default. A blue line under them says the rule back with the date the next ticket
  is born: « Every Monday at 09:00. Next ticket: Mon 19 Oct at 09:00. » The model (Haiku, Sonnet, Opus) and the
  priority (Low, Normal, High, Urgent) are buttons too, side by side; pressed again, one lets go and the ticket takes
  the runner's. The context is now « What Ponos must do every time ». A « Turn on right away » box at the foot
  replaces « Created unticked »: left empty, the schedule is created off, as before.
- **« New ticket » is a wide dialog in two columns: the brief on the left, the settings on the right.** The title is
  one large field, the brief takes the rest of the column, and two buttons under it add a « Done when » section or a
  « Files concerned » one. The type and the priority are buttons all in view — *Auto* leaves the type to the runner,
  *Urgent* is in red — the sub-type is pills shown only for a *Code* ticket, and the model sits on one line. The lines
  of help under each field are gone: a card under the settings says what the ticket will come back as — a pull
  request on the project when it has a repository, a document otherwise, and for a code ticket its commit prefix and
  its CHANGELOG section. The « Ready to run » box became two buttons: *Draft*, and *Launch the ticket* (Ctrl/⌘+Enter).
  Below 760 px the settings go under the brief.
- **A ticket's sub-type and an idea's category keep the developers' word, in every language.** The
  console in French says « ✨ Feature », « 🔒 Security », « ⬆️ Improvement », « 🧹 Chore » — not
  *Fonctionnalité*, *Sécurité*, *Amélioration*, *Maintenance* — on the card, the ticket page, the
  board's filter, the new ticket form, the statistics and the model table of the Settings; an idea is
  sorted into UX/UI, Feature, Security or Tech. They are the words of the tickets, the pull requests
  and the commits. Icons, colours, filters and what the board stores do not change.
- **The ideas window is bigger and shows an idea whole.** Up to 44 rem wide and 85 % of the screen high on a
  desktop, full screen on a phone; the title, the description and the reason for the score are no longer cut
  — what does not fit scrolls inside the card, while the badges and the ✕ / Undo / ♥ buttons stay in view.
  Ctrl/Cmd+Z undoes, and the shortcuts are written under the buttons.

- **The chat names each step, and each step opens on its own.** Under the avatar, the line says what
  Ponos is on — « Lit src/ui/hud.ts », « Lance pnpm test » — instead of « lance une commande… », with
  the full text on hover. *Voir les étapes* lists one line per step with its state (spinner, done,
  error); each line is a button that opens the command or parameters, all closed by default except a
  failed step, which opens by itself. Long output is cut with *Voir plus*, in monospace, and nothing
  is drawn until a step is opened. What a reader opened stays open as new steps arrive. The detail
  stays in the console: nothing more goes to the Notion ticket.
- **A blocked card shows Unblock and nothing else to say it is blocked.** The orange « Question for
  you » pill that sat above the button, with the same colour and the same icon, is gone. The button
  takes the icon of the cause, and its tooltip gives the cause's name, then its line of help; the
  Unblock window is unchanged.
- **A card waiting on an answer shows only its Unblock button.** The line that explained the stop
  is gone from the card; it now sits in the button's tooltip, and the badge above still says what
  it is waiting for.

- **Board cards lose their id and their robot, and the columns widen.** The `#a56f96e3` and the
  robot's head are gone from the card — the id is still on the ticket's page — so the badge and the
  date share the first line, the badge on one line and the date no longer cut. Columns are drawn at
  least 21 rem wide instead of 17.5, which also gives titles fewer lines; the board scrolls sideways
  when they do not all fit.
- **The Unblock tab reads at the size of the discussion.** The question the run asked comes first,
  large; then why the ticket is stuck, and what is already done as its own list. Text is 16 px in
  the normal colour instead of small grey, section titles are plain headings rather than tiny
  capitals, lines stop at about 75 characters, and *Send and run again* is a full-size button
  (greyed only while its field is empty). The *Unblock* button above the tabs goes while that tab
  is the one on show.

- **The console moves to react-resource-view 0.15.** Its peers stay on 0.1 (react-data-form,
  react-mini-i18n, resource-registry): 0.15 still asks for them. On a phone, the board's columns
  keep their full height rather than scrolling inside a box, so the last cards stay clear of the
  discussion's bubble.

- ***Blocked* now comes right after *In progress* on the board.** A ticket waiting on your answer
  is a ticket in progress that stopped, so it is read beside it: the columns, the status filter and
  the MCP tools all follow the one order — ready, in progress, blocked, in review, validated,
  failed, done, cancelled.
- **Unblock is a tab of the ticket's window, not a second window beside it.** *Unblock* on a card —
  and *Decide* on one in review — used to open a panel of its own over the board, and opening the
  ticket put its window under it: two windows saying the same thing. The button now opens the
  ticket's window on an *Unblock* (or *Decide*) tab, beside *Brief*, *Discussion* and *Live*,
  with everything the panel had; on the ticket itself it only switches to the tab. The tab is
  there only while the ticket waits on you, is named in the address of the ticket's page
  (`&tab=unblock`), and goes once a choice is sent, for the discussion — or the session, when one
  starts. *Abandon* says it files the ticket as cancelled when the board has that column.
- Every confirmation window of the console — making a ticket ready, validating,
  leaving a brief or the context unsaved, saving what Markdown cannot keep,
  deleting a project — is now the same window, and answers the keyboard: it opens
  on its main button, Enter does the main thing, Escape cancels, and a small
  badge in each button says so (hidden on a touch screen). A second Enter, or
  a key held down, does nothing while the first is on its way.

- **A blocked card has one button, Unblock.** The pink *Unblock*, *answer* and *make ready*
  side by side left you to guess which one was yours; the card now carries a single
  *Unblock*, drawn the way *answer* was, and its panel picks for the cause: a question
  opens on its answer field, missing access on what is missing and *it's done, run it
  again*, any other stop on its reason and running it again. Every panel ends with a field
  for an instruction of your own and, quietly, *run it again without changes* — what *make
  ready* did. The mark at the top of the card says the cause it stopped on, when the runner
  knows it, instead of *waiting for you* above a second badge.

- **The blocks chart is folded behind *Show more*.** On the dashboard and on a project's page,
  the statistics keep to the four cards and the curves; *Blocks, by cause and week* opens under
  them with a button, and the choice is kept in the browser, one for both pages.
- **The Ideas page's buttons look like the dashboard's.** *Ponos, find me ideas* and *New idea*
  take the dashboard's tinted outline button, one look shared by every page.

## [0.1.0] - 2026-10-12

### Added

- **Install with Dokploy, in one click.** A Dokploy template, in `docker/dokploy/`: the image
  pinned to a release, the four volumes, a domain on the console, and the sign-in generated
  for you. Only a way to reach Claude is asked for — the token `claude setup-token` prints,
  now read as `CLAUDE_CODE_OAUTH_TOKEN` and named as such in the console, or an Anthropic key,
  which then becomes the provider. A container given no Notion token starts on a board of
  Markdown files, `PONOS_LANGUAGE` sets the language of the reports and of the console, and
  `/healthz` answers the image's new healthcheck. A release moves the template's pin with
  the version. See *Install with Dokploy* in the README.

- **Automatic validation, project by project.** A project's page has a new *Settings* tab,
  and its first setting is *Its own automatic validation*. Off, the project follows the global
  switches, shown read only with a link to them. On, it gets its own Code, Publication, Writing
  and External action switches — started from the global ones — and its tickets follow them even
  against the global ones: merge unread on a personal project, keep the review on a client's.
  Kept in the runner's local database, so a restart keeps them. The report of a ticket validated
  automatically now says whose decision it was, the project's setting or the global one, and
  *Settings › Automatic validation* lists the projects that decide for themselves. A failed or
  blocked ticket is still never validated.

- **An *Ideas* page.** A new entry in the menu lists every idea — the workspace's and each
  project's, new, kept, thrown or turned into tickets — as cards with the title, the
  description, the *Ticket* / *New project* badge, the project's icon and name (or *Workspace*)
  and the idea's state. Filter by state and by project; *Keep*, *Throw away*, *Back to new* and
  *Turn into a ticket*, which writes the draft to Master Tickets in the idea's project.
  *Ponos, find me ideas* is there too, for the project picked in the filter, and its swipe cards
  now show the project's icon and name.

- **A "+ Ticket" button on every project, on its card and on its row.** It opens the dashboard's
  *New ticket* dialog with the project already chosen — a project with no repository
  included, whose ticket comes back as a document — without opening the project's page. The
  type is left to the runner, which deduces it from the project. A project only the
  configuration names has no page for a ticket to point at, and has no button.

- **The console from your phone, over Tailscale.** `tailscale serve --bg 8787` and
  `web.url = "https://<machine>.<tailnet>.ts.net"` in `[web]`: the console stays on
  `127.0.0.1`, and now answers that name — that one exactly — instead of a 421. Any other
  name is still turned away; with `web.url` empty, nothing changes.
- **The global context sits at the top of the Projects page.** *Context* is gone from the
  menu: the text every ticket is told first, for all the projects, is the first block of
  *Projects* — folded to a few lines in Markdown, *See all* to read it, *Edit* to write it in
  place with the same editor and the same save, and a warning before leaving with something
  unsaved. Empty, it offers to be written. `/?view=console/context/list` and `/?page=context`
  lead there, and a project's *Brief* tab links back to it (*Inherits the global context ↑*).
  Nothing changes in the API or in `context.md`.
- **Ponos in Claude by its address alone, as Leadz.** Paste `https://<your console>/mcp` in
  claude.ai or Claude Desktop, click *Connect*, *Allow*: nothing to copy. In Claude Code,
  `claude mcp add --transport http ponos http://127.0.0.1:8787/mcp`, then *Authenticate* —
  `ponos mcp token` is only for a client that cannot sign in. A new tool, `whoami`, says whose
  console it is, which client and with which access; every tool now has a title Claude shows,
  and the connector its name, its sentence and the robot. Behind a proxy or a tunnel that does
  not say it serves HTTPS, *Web console › Public address* (`web.url`) keeps the addresses
  claude.ai reads in `https://`; `ponos mcp` prints the address to paste, `ponos doctor`
  checks it. A first `GET` without a key now gets the `401` that offers *Connect*, and a
  client that says where it runs (`Origin`) is no longer refused for it. Connectors added
  before keep working. See README, *Connect Ponos to Claude*.

- **A project's brief is edited where it is read.** The *Brief* tab of a project has a
  *Modifier* button that opens the same Notion-like editor as the context and the tickets,
  with *Enregistrer* and *Annuler*; Ctrl+S saves, Escape leaves when nothing changed, and
  leaving the tab or the page with unsaved changes asks first. The brief is written where
  the runner reads it, so the next ticket of the project is told the new version. Nothing is
  overwritten silently: if the brief changed in Notion since the editor was opened, the
  console says so and offers to reload it; if the page holds what Markdown cannot keep
  (toggles, tables, mentions, embedded databases, bold and links…), it lists them and asks
  before saving.

- **Delete a project from the console**, from the list (the “…” menu of a card or a row) and
  from its page. A dialog names the project, counts its tickets, says what happens and asks
  for its name. The page goes to the Notion trash (restorable for 30 days, the toast links
  to it), the project disappears from the console at once and the runner takes none of its
  tickets any more, so no tokens are spent on it. Its ready and in-progress tickets are
  blocked with a comment (or trashed too, if you tick it); the repository, the local folder
  and the branches are never touched, its throwaway worktrees are cleaned, its ideas are
  deleted and its spending stays in the statistics. Refused while a session runs on one of
  its tickets. No bulk deletion: react-resource-view has no row selection to build it on.

- **Ponos from claude.ai, from Claude Code, from a phone: an MCP server.** The console
  answers MCP at `/mcp`: list the projects and the tasks (those waiting for you among them),
  open one with its discussion and its question, see what the runner is doing and what it
  spent, project by project — and, with the `write` scope, create a task (draft or ready, by
  the same road as *New ticket*), answer a blocked one and sort the ideas. Nothing starts a
  run, runs a command, changes a setting or deletes anything. claude.ai connects through
  OAuth (registration, consent with the console's password, PKCE), Claude Code with a token
  from `ponos mcp token`; a read-only client sees no tool that writes; every write is
  journalled with its client, and `ponos mcp list` / `revoke` show and take back the keys.
  See README, *Driving it from Claude: the MCP server*.

- **The sidebar's head, redone.** The mark and the name now sit on one axis in a head as tall as
  the bar over the page, with the same line under it so the two continue each other; the name
  takes a brand weight, and the mark is a link back to the dashboard, lit on hover and focus.

- **Every idea, on a project's page.** A project has an *Ideas* tab: all its ideas — thrown away
  and turned into tickets included — with a count per status, filters by status and by author,
  and on each one *Keep*, *Throw away*, *Back to new*, *Turn into a ticket* and *Edit*. *New idea*
  writes one by hand (title, description, project already picked), and it is never proposed
  again by Ponos. Every idea says who wrote it — Ponos with its mascot, or you by your GitHub name
  and picture — and who last reworded it. The deck's *Kept / Thrown* tab becomes *All ideas*, the
  same list. Keeping an idea and turning it into a ticket are now two things; swiping right in
  the deck still does both, and so does the MCP server's `set_idea_state`, which gains `ticket`
  beside `keep`. Ideas kept before are shown as turned into tickets, as they were.

- **A call to action with Ponos on it.** The dashboard's ideas button is now *Ponos, find me
  ideas*, in the primary colour, with the Greek mascot on its left: its flame flickers and it
  blinks at rest, it thinks (flame beacon, sparkles) when the button is hovered or focused, and
  keeps still under `prefers-reduced-motion`. While the ideas are being found, the same mascot
  searches in the dialog.
- **The console's version names its commit, and offers the update as soon as it is out.** The
  version at the top right reads `0.1.0+1a2b3c4` — the release number and the commit running,
  read from git, so it moves with every commit; hovered, it gives the full hash, the date and
  the subject. The console asks the remote itself when it starts and every 15 minutes (not with
  `runner.auto_update = false`), and the day there is something newer an *Update* button
  appears beside the version, with how many commits behind and, hovered, their subjects. Once
  the update has restarted the console, the page reloads itself onto the new version.
- **Ideas, one card at a time.** *Find me ideas* on the dashboard, and *Find me ideas for this
  project* on a project's page, open a pile of cards — title, short description, a *Ticket* or
  *New project* badge. Swipe right to keep (the draft or the project is written to the board and
  a toast links to it), left to throw away: with a finger, the mouse, the ✕ and ♥ buttons or the
  ← and → keys; a short gesture brings the card back, *Undo* takes the last one back. Ponos waits
  while a batch is written, *Ten more* closes the pile, and a *Kept / Thrown* tab keeps the
  history, from which a thrown idea can still be kept. Full screen on a phone.
- **Ideas, ten at a time — the half underneath.** Ponos can propose ideas for the whole
  workspace (new projects, or improvements across them) or for one project, in one short
  session on a light model (`runner.ideas_model`, `haiku` by default) given the project's
  brief, its README, its latest tickets — and every idea already proposed, so that none comes
  back: a title too close to a known one is dropped before it is stored. A kept idea becomes
  a draft ticket written as What / Where / Done when / Out of scope with no model, or, for a
  new project, the project itself and a first draft ticket to frame it; a thrown-away one is
  only marked so. What each batch cost is recorded in the local database. The console's API
  has the five gestures — find, list, keep, throw away, take the last choice back — and the
  screen to swipe through them comes next.

- **`[budget]`: a daily and a per-ticket spending limit.** `budget.daily_usd` stops any new
  session once the day's sessions have cost that much (the ready tickets wait, Telegram and
  Slack are told once, the console shows a banner, midnight lifts it); `budget.per_ticket_usd`
  stops a session cleanly at the limit and puts its ticket in *blocked* with the reason. Both
  empty by default. See README, *Spending limits*.

- **Ponos in a container, on your machine or on Dokploy.** A `Dockerfile` (Python 3.13,
  git, `gh`, Node and Claude Code, run as a user that is not root) and a
  `docker-compose.yml` with four named volumes — `/data`, `/workspace`, `~/.claude`,
  `~/.config/gh` — the port exposed to the proxy rather than published, and
  `PONOS_WEB_EMAIL`, `PONOS_WEB_PASSWORD`, `GH_TOKEN`, `ANTHROPIC_API_KEY` and
  `OPENROUTER_API_KEY` from the environment. In a container nothing updates itself: the
  header says a new version is a new image. The CI builds the image and runs the
  functional suite in it; a release publishes it to `ghcr.io`. See README, *Docker* and
  *Deploying on Dokploy*.

- **`ponos run --every [seconds]`: the timer, where there is no systemd.** One run each
  interval (`runner.interval_seconds` when none is given), each in a process of its own
  that takes the run lock, and the next one started at once when the configuration
  changes. It is what the container runs beside the console.

- **`claude.provider`: who answers the sessions.** `cli` (Claude Code signed in as you —
  the only one with Claude in Chrome and the wait for credits), `api_key` (an Anthropic
  key, `claude.api_key` or `ANTHROPIC_API_KEY`) or `openrouter`. A file without it works
  as it always did; `ponos doctor` says which one is in use and whether the CLI is
  signed in, and the Settings page has a section for it.

- **The first connection, in steps.** Access, Claude provider (three cards, the key
  tried before it is written, the `claude auth login` command shown and checked),
  Notion (`ponos init` from the page), GitHub, the channels, and a summary of what the
  console runs on — one line each, ok, missing or error, each leading to the step that
  changes it. The Settings page keeps the summary at its top.

### Changed

- **The dashboard's figures and *Ponos, find me ideas* share one line.** The button is no
  longer alone on a line of its own above the strip: it sits at the strip's right end, a quiet
  outlined button with a small mascot. The three figures read the same way — the number, what
  it counts, then a quieter note, in one face and one size, a rule between them. Where the
  strip is narrow the button shows the mascot alone, its words in a tooltip, and on a phone
  the figures stack one a line.

- **Settings in six pages you can find your way in.** Twenty-two sections at one rank become
  six pages, each at its own address: *General* (state of the runner, languages, test mode,
  updates, console access, logs), *Ticket source* (where the board lives, Notion's token,
  workspace page and tickets database — every column, property, database and type name folded
  under *Advanced mapping*), *Execution*, *Models and costs* (every model choice in one place,
  the automatic choice drawn as a small level × type table), *Code and repositories* and
  *Communication*. One column of cards, a bold label, one line of help and the rest behind a
  « ? », switches for yes/no, a unit beside every number, a *Browse* button for paths, a search
  that opens the right page and unfolds what hid the field, and the `config.toml` keys hidden
  until *Show keys* is on. A token the environment gives says so. `config.toml` does not change;
  `runner.notify` is now drawn as *Notify on this computer's screen* (`notify.desktop`), which
  already fell back on it, and saving that switch removes the old line. An old link to a
  section opens the page it is on.

- **A project's page is as wide as the dashboard, and its tickets are the dashboard's list.**
  The page takes the whole width and the same margins; the *Tickets* tab draws the same
  react-resource-view list as the dashboard, kept to the project, as a board (one column per
  status) or as a table (id, title, status, priority, type, cost, last modified) with a search
  and filters on status, priority and type. The layout picked is shared with the dashboard, and
  *New ticket* opens the dashboard's form with the project already chosen. The *Brief* tab
  keeps its content, at the same width. The table has no column sorting yet: react-resource-view
  has no sort for a local source, to be asked of the library.
- **The Settings action bar, redone.** On every section, *Cancel* (secondary) and *Save*
  (primary, blue, with a spinner while it saves and a clearly greyed state when nothing
  changed) sit on the right; on the left a quiet status says *No changes*, *Unsaved changes*
  (with an accent dot), *Saved ✓* for a few seconds, or the error in red. The bar sticks to the
  bottom of the screen only while something is waiting, and the browser asks before you leave
  the page with unsaved settings. Empty fields no longer say "nothing": the instructions files
  show *Ponos's default instructions*, the others *not set*.

- **The console and the site are blue, the robot's blue.** The lime accent is gone: buttons,
  the active sidebar item, focus rings and the sign-in page take the mascot's blue (a deeper
  shade of it in the light theme, so white text stays above 4.5:1). *In progress* and the
  *Created* curve move to a cyan so an action is never mistaken for a status, and the green
  of *ready* is a true green. Cards on the board no longer carry a coloured edge on the left;
  the column and the badge say where a ticket stands.

### Fixed

- **A worktree directory left full of root-owned files no longer blocks its ticket.** The
  containers of a project (`vendor/`, `var/`, `.vite/`…) write files the runner's user cannot
  delete, so `git worktree remove` left the directory behind and the ticket came back with
  "could not create the worktree". A directory with no `.git` is now emptied — through a
  `docker run --rm … find -delete` (no shell) when it holds somebody else's files, or moved
  to `leftovers/` in the state directory when there is no Docker — both when a worktree is
  removed and when one is created. `ponos clean` empties these residues without `--force`
  and leaves every real worktree alone; `ponos doctor` counts them. A directory with a
  `.git` is never touched by it.
- **A ticket moved back to ready is played again, even by the pass that already ran it.**
  A pass refills itself and can last for hours, and it held out every ticket it had ever
  started: a ticket played, blocked and moved back to ready waited until the pass ended,
  with nothing to say why, while every new ticket went straight through. It is now held
  out only while a session of the pass is still on it, then replayed on its branch and
  pull request. Every ready card in the console says what it is waiting for, and a local
  claim whose ticket is no longer in progress is dropped at the top of the next pass.

- The model the runner chooses for a ticket with none is now written in its
  Model column, not only announced in the comment, so boards, filters and
  statistics show it. A model somebody wrote is never overwritten, and a board
  without the column goes without. A failed write is a line in the log.

- **The cost of a blocked or failed session is now written in Cost.** Only finished tickets
  recorded theirs, so those sessions were missing from the board, the history and the
  statistics.

### Security

- **Outside its machine, nobody claims a console without its installation code.** An
  unclaimed console draws a code when it starts and prints it beside its address; the
  first connection asks for it from any other address, or through a proxy, and refuses
  outright when none was drawn. Behind HTTPS (`X-Forwarded-Proto: https`) every cookie the
  console sets is `Secure`.

- **No secret in `config.toml` any more.** The Notion token, the console's token and
  password, the Telegram and Slack bot tokens and the Anthropic and OpenRouter keys are
  read from the environment or from `secrets.env` beside the configuration (`NAME=value`,
  created `600`; `PONOS_SECRETS` moves it), never from `config.toml` — which is copied into
  images, onto volumes and into tickets. The variables: `PONOS_NOTION_TOKEN`,
  `PONOS_WEB_TOKEN`, `PONOS_WEB_PASSWORD`, `PONOS_TELEGRAM_TOKEN`, `PONOS_SLACK_TOKEN`,
  `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`. The console, `ponos init` and the installer
  write a secret there; a secret an older version left in `config.toml` (or its `.bak`) is
  moved out by the next launch, which says so on stderr — or says which variable to set
  when it cannot. `ponos doctor` checks both files. The Docker documentation passes every
  secret as a Dokploy variable.

- Console, a project's page: two tabs, **Tickets** (the default — the project's tickets, and a form to add one that is attached to the project) and **Brief**; the tab is in the address (`&tab=brief`), so a reload or a pasted link comes back to it. "On this machine" now shows the clone's real path, with a button to copy it — or says the project is not cloned yet.

- **A project's page has its own statistics.** The same folding band as the
  dashboard's — same periods, same four cards, same two curves — limited to that
  project's tickets and to what their sessions spent, with the average cost of a
  closed ticket under *Spent*. The third panel is the tickets created, by column
  (*by project* means nothing for one). `/api/statistics` takes an optional
  `project`; the dashboard's figures are unchanged.

### Changed

- **The site has a domain of its own: [the-ponos.app](https://the-ponos.app/).**
  It is still the same page on GitHub Pages, now at the root of its own address;
  `cardona.digital/ponos/` and the older `cardona.digital/ticket-runner/` send
  every link, sub-pages included, to the same page there.

- **The board's first column is always the drafts, and it is the only one for
  them: *Brouillon* in French, on the left, before *Ready*.** A ticket with no
  status, one whose status is `draft`, and one under a status nobody configured
  all sit there, so no ticket is hidden and no "No status" column is drawn at
  the end. Moving a card to the drafts writes that option, or clears the status
  on a board that names none. The list view says the same, in the same order.

- **A ticket's page is three tabs again, and its session reads in broad lines.** *Brief*
  (the facts and the page), *Discussion* and *Live*: a ticket in progress opens on *Live*,
  one waiting on you on *Discussion*, any other on *Brief*, and the tab you pick is kept in
  the address. *Live* shows what the agent says, one line each; the commands, tool calls
  and errors that followed are folded under it, with how many steps, how long, and a red
  mark when one failed — *Unfold everything* opens them all, and a line you opened stays
  open while the session goes on. A finished session reads the same way.

- **The console says which model a ticket really runs on.** Where it used to read
  “Claude Code's own · default”, a ticket's page now reads `claude/opus · default`: the
  model the last session announced about itself (the journal keeps it with each run),
  else the one the ticket or the runner names, else Claude Code's own setting — and
  “Claude Code's default, unknown before the first session” when nothing can be said yet.
  Models are written `provider/model` everywhere (`claude/haiku`, `deepseek/r1`; an
  OpenRouter `vendor/model` is kept as it is) — on the card, in the table, in the list of a
  ticket's runs — with the full identifier as a tooltip on the page.

- **Claude Fable is off unless you turn it on.** It costs far more than Opus — one
  session of it cost more than a day of Opus ones — and it arrived unasked, through the
  heaviest level of the automatic choice or an escalation. With the new
  `runner.use_fable` (`false` by default, also in the console's settings, *Models and
  usage*), nothing the runner starts runs on Fable: those levels run on `opus`, an
  escalation stops there, a session begun on Fable carries on on Opus, and a `Model` of
  `fable` on a ticket or its agent runs on Opus with a line in the ticket's report that
  says why. The console's chat and every other session follow the same rule. **An
  existing `config.toml` without the key loses Fable**: add `use_fable = true` to keep
  it. `ponos doctor` says which it is.

### Added

- **A ticket with no Model no longer runs on the heaviest model by default.** The
  runner chooses one before the session starts, by rules that cost nothing: the type
  sets the level it starts from, the size and the wording move it — a title that asks
  to *remove*, *rename* or *reword* something drops to `haiku`, a bug or a feature runs on
  `sonnet`, an *audit*, a *migration*, a *refactor* or a hard bug on `opus`, and a long
  request full of them on `fable` — and an Urgent or High ticket never gets the
  lightest. The model and its one-line reason go into a comment on the ticket
  (*🧠 Model chosen automatically — haiku*). A ticket whose chosen model failed runs
  one level higher when it comes back, once, and says so. A Model written on the ticket
  or on its agent is always taken as written. `runner.auto_model` turns it off, and the
  four levels' models and each type's starting level are set in `config.toml` or in
  the console's settings (*Models and usage*); the local journal now remembers each
  run's model. Works the same on a Notion board and a Markdown one.
- **Every run, and every step of it, in the local database — and the console reads
  them from there.** Each session on a ticket is a run in `ponos.db`, each step a row
  (what the agent said, the tool and what it was pointed at, the failures, the time,
  the cost when known), written as it happens and closed on what the ticket came to.
  The ticket's **live** tab reads it a page at a time — *Earlier steps* goes back
  further — follows the run in progress, and offers every earlier run of the ticket,
  with how it ended and what it cost. The Notion page keeps only the agent's sentences
  and the result. `ponos logs <ticket> --runs` lists a ticket's runs, and `ponos logs
  <ticket>` finds its newest log through them. Notion, Markdown or both: the journal
  is the same.
- **A local database, `~/.local/state/ponos/ponos.db`, with numbered migrations.**
  The foundation for what the runner will keep about its own runs: SQLite (in
  Python's standard library, so still nothing to install), in WAL mode so the
  timer and the console can write it at once. Its schema version is applied
  forward on opening, one migration per transaction, safely when two processes
  start together; a file from a newer Ponos is refused untouched. `ponos doctor`
  checks it opens and says its schema version. Tickets stay on the board.
- **The runner's notes to itself now live in that database.** The history, the
  claims, the replay counts, the conversations, the credit waits, the Markdown
  mirror's stamps and journal, and the index of project pictures were a dozen
  JSON files; they are tables now, each brought in by its own migration. An
  installation that has the files keeps everything — same history and
  statistics, same conversations, same claims: each file is read in once on the
  first start and renamed `<name>.imported`, never deleted. Session logs stay
  files.
- **The console opens in the language you set, and the runner says everything in
  it.** A new key, `runner.app_language` (`en` or `fr`), is the language the
  console opens in and the one its sign-in and set-up pages are written in;
  empty, it follows `runner.language`, so `language = "fr"` alone puts the
  reports *and* the console in French. The FR / EN select still switches the
  console, and a choice made there stays with the browser. Both empty: nothing
  changes. The Settings page offers the key, and `ticket-runner doctor` says
  which language each is in — and warns about a name it does not speak, which
  it reads as English.
- **What the runner still said in English follows `runner.language` too**: the
  body of the pull requests it opens, the note on a branch a ticket already had,
  the line a ticket born of a schedule opens with, the « more than 300 steps »
  line of the folded block, the out-of-credit and reserve notifications, the
  button of a desktop notification, and an answer relayed from Telegram, Slack or
  the console (« Répondu depuis Telegram par Salva. Oui — vas-y… »). An answer
  relayed in English before the change still wakes its ticket. A session told a
  language is now told to ask its questions in it as well, even on a ticket
  written in another, with `RESULT:`, `ok` and `blocked` left as they are.

- **Drafts have a column of their own.** A board that already keeps an option
  for tickets still being written — Master Tickets says `draft` — can name it
  under `[notion.status]` as `draft = "draft"`: the console draws those tickets
  in a *Draft* column (*Brouillon* in French), first on the board, and
  *New ticket* with *Ready to run* off writes that status rather than none. The
  runner never picks a draft up. Optional, with no default: left out, nothing
  changes, and no status is ever created in Notion. `ticket-runner doctor`
  checks the option exists and is none of the runner's own, and the Settings
  page offers the key.
- **The runner cleans up after itself.** Once a day, a pass applies the
  retention on its own — no more `ticket-runner clean` to remember: session
  logs older than `runner.log_retention_days` (they were only dropped by a pass
  that had a ticket to run), and, with the new `runner.clean_done_worktrees`
  (on by default), the worktrees and scratch directories of tickets the board
  says have been **done** for that long, plus the scratch directories of tickets
  no longer on the board. A ticket in progress, blocked, failed or in review
  keeps its directory however old; a done ticket's worktree with uncommitted
  changes is kept; no branch is ever deleted. The settings page of the console
  shows the space taken by worktrees, logs and scratch, with a **Clean up**
  button that applies the same retention now (refused while a run is in
  progress), and `ticket-runner doctor` says both in a new *Disk* section.
- **Priority, type and model from the *New ticket* form.** Three optional
  selects, shown only for the columns the board has — Markdown boards have all
  three: the priority and the model the runner acts on, then whatever else the
  board offers, and the four types as the board spells them. An empty type is
  still deduced by the runner before the ticket runs. Under *Ready to run*, the
  form now says that ticked, a session starts at the next pass, and within how
  long; **Ctrl+Enter** (⌘+Enter) creates the ticket from any field, the brief
  included.
- **A ticket's discussion is on its page.** The ticket page has a third tab,
  *discussion*, beside *the brief* and *live*, with the number of messages on
  it: the runner's reports and questions, your answers, oldest first. You answer
  in the same message bar as the console — Enter sends, the microphone dictates.
  A ticket waiting on you — in *Blocked*, or with a question a run asked that
  nobody has answered — opens on that tab, and its card on the board says
  *waiting for you*. The bubble in the corner now opens the console on every
  page, a ticket's included, instead of quietly becoming that ticket's
  discussion.
- **Keyboard shortcuts in the console.** **Ctrl+K** (⌘K on a Mac) opens a
  command palette from any page: the pages, the projects, the tickets on the
  board, and three actions — a new ticket, the console, a resynchronisation —
  found by typing and opened with Enter; Escape closes it. **Ctrl+J** (⌘J) opens
  and closes the console, with the cursor already in its message bar, and hands
  the focus back to where it was when it closes. Both work from inside a field;
  a magnifying glass in the bar opens the palette for the mouse, and its tooltip
  and the bubble's say the keys.
- **Ponos thinks, the steps fold, and a turn can be stopped.** In the console's
  conversation with the workspace, a turn in flight shows Ponos thinking and one line
  about what the session is on — *reading api.py…*, *running the tests…*, *fixing an
  error…* — with the time spent, still under `prefers-reduced-motion`. The Bash lines and
  the Tracebacks no longer fill the conversation: they are folded under *Show the steps*,
  closed by default, whose line keeps the count, the time, the cost and a red dot for the
  steps that failed. While it answers, the arrow of the bar becomes *Stop* (or Escape from
  an empty field): the session and every command it started are ended, the conversation
  says *stopped by you* with what had been done, and the next message carries on in the
  same session.
- **Force validated, one type of ticket at a time.** Four boxes in *Settings ›
  Automatic validation* — Code, Writing, External action, Publication — or
  `force_validated_<type> = true` under `[runner]`, all off by default. Ticked,
  a ticket of that type no longer waits in *In review*: once its session has
  succeeded, a Code ticket's pull request is opened, its CI waited for and
  merged with `merge_method`, and a Publication is published straight away —
  then *Done*, with *Validated automatically (Force validated: …)* in its
  report. A merge GitHub refuses leaves the ticket in review, with the reason in
  its report and on its card. A failed, blocked or out-of-credit ticket is never
  validated, and a ticket already in review is left alone. Writing and External
  action already end in *Done*: their boxes change nothing today.

- **The console updates Ponos in one click.** The day a newer version is
  waiting, the version at the top right turns into a button: it names the
  installed version and the new one, links the release notes, and asks before
  anything happens. The update then runs with every step shown — downloading,
  installing, restarting — and the page reconnects on its own to the new
  version. A ticket in flight is never cut: the update waits for it (*Update
  after the ticket*, and can be called off meanwhile), and no ticket starts in
  between. Opened from another machine, the dialog gives `ticket-runner update`
  to copy instead.

- **The console's message bar takes photos, videos, documents and your voice.**
  *Talking to your machine* is now one rounded bar with the files above the
  words, a **+** to attach, a microphone, and a round arrow to send. A
  screenshot is pasted, a file dropped anywhere on the drawer or picked with the
  **+** — images, videos (mp4, webm, mov) and documents (pdf, txt, md, csv,
  json, docx, xlsx), up to `web.attachment_max_mb` (25 MB) each — and the
  workspace reads them from where they are kept, under the runner's state: an
  image or a PDF as it is, a video through frames `ffmpeg` takes along it (and,
  without `ffmpeg`, it says it could not see the clip). The microphone records
  (Alt+Shift+M), has the recording transcribed by OpenRouter in the runner's
  language, and puts the text in the bar to be read over before it goes —
  `web.send_after_transcription` sends it straight away. Without an OpenRouter
  key it is greyed out and says so. Your files show as thumbnails above your
  message and open in full with a click; *new conversation*, now a pen at the
  top of the drawer, deletes them, and `web.attachment_days` (7) removes what a
  conversation nobody closed left behind. `>` still runs a command, now with
  the verbs offered as you type.

- **Every project has a picture in the console.** The cover and the icon of its
  Notion page are the project's thumbnail in the list and the banner of its page
  — or its initial on a colour of its own, when it has neither. *Change the
  image* uploads a file, takes a pasted address or an emoji, and the picture
  becomes the page's cover or icon in Notion; one changed in Notion shows in the
  console at the next reading. Pictures stay on screen for as long as the
  console is open — a copy is kept on disk, since Notion's own links expire
  within the hour — and a change Notion refuses is kept and sent again rather
  than lost. On a Markdown board, the picture is a file beside the project's.

- **The console and Notion, kept in step — and saying when they are not.** The
  console reads what changed since its last read, reaching two minutes back
  (Notion's `last_edited_time` is to the minute: four moves in one minute all
  read `09:32:00`), and the whole board every five minutes and on demand; what
  the full read finds the others missed is counted and shown. A move made from
  the console is queued on disk, checked against the page first, retried with
  a growing wait, confirmed by reading the page back, and the card says
  *waiting*, *not sent* or *changed in Notion meanwhile* until it is settled.
  The bar says when the board last agreed with Notion, and its button now
  resynchronises. Every change seen, confirmed or refused is written in
  `sync.jsonl`.

- **A statistics page in the console.** *Statistics* in the menu opens on the
  last month — or seven days, three months, two dates of your own — with the
  tickets open on the last evening, closed and created over the period, and
  what the sessions spent; under them, a point per day for what came in, what
  went out, the open stock and the running spend, and the period's new tickets
  by status and by project. A closing is dated by the runner's history when the
  runner made it, and by the page's last edit in Notion otherwise; the page
  says how many of each.

- **A validated pull request that conflicts is resolved, not left to you.**
  “Pull Request has merge conflicts” used to block the ticket. Now the runner
  asks GitHub first, replays the branch onto its base in a worktree of its own,
  and hands the conflict to a session told to keep both sides — the ticket's
  work and what was merged meanwhile — to regenerate lockfiles rather than merge
  them, and to run the project's checks. The result is pushed with
  `--force-with-lease`, the pull request's CI is waited for, and the merge is
  asked again; the pull request and the ticket both say which files conflicted
  and how each was resolved, and the session's cost is added to the ticket's.
  A conflict that is a decision, checks that stay red, commits somebody else
  pushed, or a base still moving after two replays block the ticket with the
  question, and the resolution reached so far is pushed on a branch of its own.
  `runner.resolve_conflicts`, `resolve_conflicts_except`, `resolve_model` and
  `checks_timeout_minutes` configure it. See the README, “Ten tickets on one
  repository”.
- **A running ticket is followed on the ticket, not on a page of sessions.**
  The console's *Live* page listed sessions by the id of their log, and nothing
  said which ticket `24f9704c` was. A ticket's page now has a *live* tab — the
  one a ticket in progress opens on — with its session's journal as it is
  written: what the agent says drawn as prose, each tool call folded to one
  line with the worktree's path shortened to `./`, the scroll following the end
  until you scroll up. A finished ticket shows its last session there,
  read-only. On the board, a card in progress pulses, counts its steps and says
  what it is on; the runner's figures — sessions, timer, tickets handled and
  their cost — are a strip over the columns. The *Live* page and its menu entry
  are gone, and its old address leads to the board.
- **A ticket has a type, and the runner works it out when you did not.** A new
  `Type` column — *Code*, *Writing*, *External action*, *Publication* — says
  which road a ticket takes. Left empty, a short session on a light model
  classifies the ticket before it runs, writes the type into the column and the
  reason into a comment; a type you chose is never overwritten. When the guess
  is unsure, or hesitates with *External action* or *Publication*, nothing runs:
  the ticket is blocked with the question. An external action works without a
  repository, stops at its first doubt and logs what it did; a publication is
  prepared into *In review* and published only once you move it to *Validated*.
  `ticket-runner init` adds the column; a board without it runs as before. See
  [The type of a ticket](guide/board.md#the-type-of-a-ticket).

- **The console wears the robot too, and it shows what the runner is doing.**
  The mascot of the landing page is now the console's mark and favicon, and a
  face at the right of the bar that changes with the runner as it happens:
  asleep on an empty queue, thinking while a ticket is claimed, busy while a
  session types, jumping when a ticket comes back, upset when one is blocked or
  the connection drops. Every card of the board wears one in the mood of its
  column — only the ones in progress move, so a board of a hundred stays calm —
  and so do the session panels, the empty lists, the loading and error pages
  and the toasts. A seventh state, `waiting`, says a person has the next move.
  One file for both: the console bundles the landing page's own component.

- **ticket-runner has a face.** A small robot, on the landing page and in its
  favicon, whose mood follows a ticket: thinking when one is claimed, busy while
  Claude Code types, jumping when the pull request is open, sad when it is
  blocked, asleep when the queue is empty — and a bar to make it react. One SVG
  in layers, coloured by CSS variables, light and dark, still under
  `prefers-reduced-motion`; a new state is one entry in a table. See
  [Mascot](CONTRIBUTING.md#mascot).

- **The console sets itself up on the first connection, and nobody has to find a
  token again.** A token protects an installation that is already set up; a
  fresh one has nothing to protect yet, and being sent to look for a secret on
  disk before you may type your own was the wrong way round. So a console
  **nobody has claimed** — no `web.token` chosen, no email and password set —
  now serves a form rather than a door, and `http://127.0.0.1:8787` is the whole
  of the address. One press does the installation in the order somebody would
  say it: the email and password that open the console from then on, and which
  sign the browser in there and then rather than asking for what was typed a
  second ago; the Notion token and the link of the page you shared, under which
  the five databases are built by the very code `ticket-runner init` runs; the
  rules that reach every session before the project's brief and before the
  ticket; and a Telegram bot token, whose chat id is read back from the bot so
  there is nothing to look up. Everything but the first pair may be left for the
  Settings tab, and a step that fails is said in the report rather than undone —
  pages created in somebody's Notion are not a thing to roll back. That first
  pair is also what closes the page for good: the next request is asked to sign
  in. An unclaimed console is necessarily on loopback — `serve` refuses any
  other host without a token or a sign-in — so the first browser to arrive is
  somebody sitting at that machine; on a machine you share, set `web.token` or
  the sign-in before starting the console, and `serve` says which of the two
  states it is in. An installation that already works and has never had a
  password is unclaimed too: the same form, with the Notion half already done,
  at `/setup`.

- **A project is a page you open and change, in the layout that suits the
  question.** The console's Projects screen only ever read: a list of what this
  installation knows of, and a link out to Notion for anything you wanted to
  change. But a project is where every ticket of that project starts from — its
  repository, and the brief that gives an answer your voice rather than
  nobody's — so it is now a resource like the board. Click a project and you get
  its page: what it declares, how many tickets point at it, and the brief
  itself, drawn rather than shown. *Edit* opens the four fields the page holds —
  the name, the repository, the path on this machine, and the brief — and what
  is written goes to the column your page already carries, `Repository`,
  `github` or `repo`, rather than to a second one beside it. The list comes in
  **two layouts**, and the one you are on is in the address: *cards*, to
  recognise a project by its name and its shape, and *table*, to compare them —
  which of these eleven has no repository is a question a grid of cards will not
  answer. A project only `[projects]` names has no page to write to: it says so
  and points at the settings, where that line lives. The old `/?page=projects`
  still lands on the list, so a link you kept goes on working.

- **The runner stops before the subscription is spent, and leaves you a share of
  it.** A runner left to itself would chew through every window it is given, so
  the terminal you open yourself at five o'clock finds nothing left.
  `runner.credit_reserve_percent` is the share it refuses to touch — 5 by
  default, so nothing new is started past 95 % — read off the same two figures
  Claude Code's own `/usage` shows, the session window and the week, whichever
  is the more constraining. What is already running is never killed: it
  finishes, because stopping a session halfway spends what it has already cost
  and gets nothing for it. What costs no credit carries on throughout — a pull
  request you validated this morning is still merged this afternoon — and that
  is the whole difference between this line and a spent window, which stops the
  pass outright. The reading is taken again at every free place rather than once
  a pass, since the sessions in flight are what fills the window. `0` spends the
  lot, as before this existed; `50` is the most it accepts; and a reading nobody
  can take — no Claude Code store, a payload whose shape changed — is one
  warning and the old behaviour, never a runner that stopped working because it
  could not find a JSON key. The setting is a field of the console's Settings
  tab, under *The run*.

- **A ticket the credit ran out under is ticked, not moved to a column of its
  own.** *Blocked* is the column that means **you** are needed — the agent asked
  a question and is waiting for an answer — and letting "come back at six" into
  it made the one column anybody has to open stop saying anything. But an eighth
  column was the wrong answer to that: nothing *happened* to the ticket, and
  moving it says something did. So the tickets database gains a checkbox,
  **Waiting for credit**: the ticket stays exactly as ready — or as validated —
  as it was, ticked while the window is spent and unticked by the write that
  claims it. The pass that has credit again takes the ticked ones *before*
  anything else, because they are the ones already half done. It picks their
  session back up rather than beginning the ticket over — the conversation is
  sent one message saying the window rolled over and its own half-done work is
  still on disk, not the whole frame a second time, and a session Claude Code no
  longer has falls back to a fresh one. What was queued behind a spent session
  is ticked the same way rather than sitting in *Ready* looking like a runner
  gone quiet. Being a property and not a status option is also what makes it
  reach a board built before it: `ticket-runner init` adds it to an existing
  database, where an option on a real `status` can only be typed in by hand.
  Without it nothing breaks — the credit is waited out silently, as before.

- **Ten tickets on one repository stop making nine conflicts.** The base branch
  does not wait for a session: the first merge lands, and every session still
  running is opening a pull request against a `main` of an hour ago. The branch
  is now replayed onto its base between the commits and the push, so what opens
  is a pull request on top of what the repository holds *now* — and a rebase
  that hits a conflict changes nothing: the branch goes back as the session left
  it, the pull request opens all the same, and the conflict is written on the
  ticket instead of being discovered on GitHub. The same gesture answers a
  *validated* merge GitHub refuses for being behind: the branch is replayed,
  pushed with a lease on the very commit that was replayed, and the merge is
  asked once more before the ticket is called stuck. A refusal a rebase cannot
  answer — a check still red, a review still missing, a branch policy — is left
  exactly as it came. `runner.rebase = false` gives back the old behaviour.

- **A machine that answers to two GitHubs.** `gh` only ever has one account
  active, so a pull request on the other one used to be refused for reasons that
  read like a bug: a repository GitHub says does not exist, a merge nobody is
  allowed to make. A new `[github]` table says which owner is worked under which
  account — `"northwind" = "dev-northwind"` — and everything that leaves the
  machine about that repository, the clone, the push, the pull request, the
  merge, the question “has this been merged yet?”, goes out under it. Log each
  account in once with `gh auth login` and they stay signed in side by side; no
  token is written into the configuration, it is asked of `gh` when it is
  needed. An owner nobody names is worked under whichever account `gh` is signed
  in as, so one GitHub means nothing to configure — and a line naming an account
  `gh` does not know is not a ticket's problem: the command runs as the active
  account, and `ticket-runner doctor` says the line is dead. The table is a
  section of the console's Settings tab, *Your GitHub accounts*.

- **The runner can live without Notion: the board as Markdown files.** One line —
  `storage.mode = "markdown"` — and projects, the standing context, the schedules
  and the tickets are read and written as files, properties in a YAML
  frontmatter and the content as Markdown under it, in a directory you can put
  under git. Nothing reaches the network: no token to create, no page to share,
  no integration to grant capabilities to, and `ticket-runner doctor` stops
  asking Notion who you are. Everything after that is unchanged — the queue, the
  claim, the worktree, the session, the report, the discussion on a ticket — for
  the reason this was worth doing at all: the runner now talks to a board
  through one interface (`store.py`), and which board answered is decided in one
  place. `notion` stays the default and behaves exactly as it always has.

- **The console can see every project, rewrite the standing context, and write a
  schedule.** Three screens, and they are what makes a Markdown-only
  installation self-sufficient. *Projects* lists every project this installation
  knows of — the board's own and the ones only `[projects]` names — with what
  each declares and where it landed on this disk. *Context* shows the text that
  reaches every ticket before the ticket itself, as the agent gets it, and saves
  it: it replaces rather than appends, because a context is a value, not a
  history. *Schedules* is no longer read-only — a row opens into a form for the
  six columns a schedule is written in, never the three a pass writes back, and
  a new schedule is created unticked whatever the form said.

- **Notion and Markdown, kept in step.** `storage.mode = "both"` reconciles the
  two before every pass and writes to both in between, so a ticket claimed at
  14:02 is not still reading *Ready* in the files while a session works on it. A
  page changed on both sides since the last reconciliation is a conflict:
  `storage.conflict = "newest"` keeps the later edit and writes the other into
  `~/.local/state/ticket-runner/sync.jsonl` with both timestamps and the name of
  the side that won. Nothing is ever deleted — a page that disappeared on one
  side is journalled and left alone on the other — and a page that never existed
  on the other side is created there, which is what makes the switch work from a
  board that is already full. `ticket-runner sync` does it on demand,
  `ticket-runner sync --journal` says what past ones did.

- **A project created from its GitHub link alone is cloned, not refused.** Until
  now, a `Repository` property that matched none of the clones under
  `workspace_root` put the project back with "no repository could be found" —
  and the only way out was to go and `git clone` it yourself. Now the first
  ticket that needs it makes the clone: `gh repo clone` where `gh` is there, so
  a private repository comes down under the same authentication the pull
  requests go out under, plain `git clone` otherwise, into `workspace_root`
  under the repository's own name. The ticket then runs in it exactly as in one
  you had all along, and its comment says where the folder came from. Nothing
  else changed: every way of matching a clone you already have is still tried
  first, a remote two clones answer to is still a question rather than a third
  copy, and only the run about to work on a ticket downloads anything —
  `ticket-runner projects`, `ticket-runner next` and a dry run read the board
  and fetch nothing.

- **The console opens with an email and a password, not with a token.** Set
  `web.email` and `web.password` — in the configuration, in the *This console*
  section of the Settings tab, or in `TICKET_RUNNER_WEB_EMAIL` and
  `TICKET_RUNNER_WEB_PASSWORD` for a server where a secret has no business being
  written down, the environment winning over the file — and
  `http://127.0.0.1:8787` becomes a bookmark that works: the page asks for the
  two instead of for a token you had to find again on every browser. The cookie
  it leaves is derived from them rather than drawn, so a console that restarts
  does not sign you out, and changing the password signs out every browser at
  once. Setting the two also unlocks a non-loopback bind, exactly as a token
  does, and deserves the same suspicion — behind that port sits
  `bypassPermissions`, and a wrong answer costs a second on purpose. The token
  does not go away: it stays what a script carries, what `serve --print-token`
  prints, and what the dev server's proxy borrows. It just stops being what
  *you* carry.

- **The console speaks French, and asks nobody which.** It reads the browser first —
  `Accept-Language` is a setting somebody actually made — and where that says nothing
  useful the time zone answers for it: a machine on Europe/Paris opens in French. The
  select at the right of the bar, under the flag, is how you disagree with the guess, and
  the choice is kept in `localStorage` like the theme. It holds everywhere: the menu, the
  pills in the bar, a ticket's page, the discussion under it, and the settings tab down to
  the sentence under each of its seventy fields. What stays in its own language is what
  belongs to somebody else — a ticket's title and the columns of your board are Notion's,
  the output of `> status` is the CLI's, and a report a run wrote follows `runner.language`
  as it always did. English is unchanged: it is the language the console is written in, and
  a console nobody switches is the console it was.

- **An OpenRouter key, and every other model comes within reach.** `openrouter.key`
  in the configuration — or the *Every other model* section of the console's
  Settings tab, where it is a secret like any other — and every session the
  runner starts carries it as `OPENROUTER_API_KEY`. Nothing about the runner
  changes: the key is simply *there*, so a ticket can have a GPT write the copy,
  a model transcribe an audio file or another make the video, and pay for it,
  without the runner having to know what any of those are. The second switch,
  `openrouter.route_sessions = true`, runs the sessions themselves on it: Claude
  Code then talks to OpenRouter rather than to Anthropic, and every model named
  — a ticket's Model column, an agent's, `runner.model` — becomes an OpenRouter
  slug, `openai/gpt-5` or `anthropic/claude-sonnet-4.5`. Two things travel with
  that one, and the README says so where it is offered: the CLI is authenticated
  by a token instead of as you, so Claude in Chrome does not load, and the bill
  is OpenRouter's rather than the subscription's, so there is no window left for
  `runner.wait_for_credits` to wait for.

- **The runner waits for the credits instead of failing on them.** A Claude
  subscription is metered in windows, and a spent one used to cost a whole
  board: every ticket the runner touched came back as a failure with a log to
  read, and by the time the credits returned there was nobody left to put any of
  them back. Now a session that dies on the quota puts the ticket back where it
  was taken from — *ready* for work, *validated* for a publication, branch and
  worktree untouched — and nothing at all is started until the window rolls
  over. The wait lasts as long as Claude Code said it would, or a quarter of an
  hour when it did not say; `ticket-runner status` and the console's header both
  show how much of it is left. `runner.wait_for_credits = false` brings back the
  old behaviour, which is what an `ANTHROPIC_API_KEY` runner wants.

- `runner.language`, and the runner answers in it. `"fr"` — or `"FR"`, or
  `"fr-FR"`, or `"français"` — and every report under a ticket, every question a
  blocked one asks and every line that reaches Telegram or Slack comes back in
  French. The setting also travels into every prompt, so the summary at the top
  of a report, the document a ticket with no repository produces and the answers
  given in the comments follow it too; commit messages and code keep the
  language the repository already uses. Empty stays English *and* keeps meaning
  "nobody decided": each session goes on answering in the language of the ticket
  it was given, exactly as before.

- **A schedule's context is written from the console, and every Markdown field
  is an editor.** The page body of a schedule — the brief copied into every
  ticket it makes — was the one part of a row the console could not touch: the
  form wrote its columns, and the text meant opening Notion. It is the last
  field of that form now, read from a new `GET /api/schedules/<id>`. And the
  four places the console writes Markdown — that context, the standing
  context, a project's brief, a new ticket — are no longer a text area but
  [Milkdown](https://milkdown.dev)'s Crepe: `/` for a block, a handle to drag
  one, a bar over a selection, `#` and `-` turned into what they mean as they
  are typed. Markdown is its model rather than an export of it, so what reaches
  Notion or a Markdown board is the text that was typed. It is fetched the first
  time such a field opens, not with the console.

### Changed

- **A ticket opens in a window over the board.** A click on a card — or on a
  ticket's title in the table — no longer leaves the board: the ticket is drawn
  in a window in the middle of the screen, the whole screen on a phone, with
  its short id and title at the top and two buttons beside them, one to its
  full page and one to close. The cross or Escape puts you back on the board
  where you were. The page itself keeps its address, so a shared link, the
  palette and a notification still open it, and a middle click on a card still
  opens it in a tab. The table's *read* button goes: its title is the way in.

- **A ticket run again is no longer briefed on its earlier runs.** Each run
  leaves its live block on the page, and a ticket sent back to *Ready* — a
  retry, an unblocking — used to hand all of them to its next session: tokens
  paid for steps already taken, and old sentences an agent could read as
  instructions. The brief is now read without them, wherever a page is read as
  one — a ticket's session, its reply to a comment, a conflict to resolve, an
  agent, a project, a schedule — and Notion is not even asked what they hold.
  The console's view of a ticket leaves them out too, and opens a request
  lighter for each of them. The report a run ends on — the pull request, the
  answer written into the page — stays part of the brief. On a Markdown board
  the story of a run is now written between `<!-- ponos:live -->` and
  `<!-- /ponos:live -->` and left out the same way; one written before this
  version has no fence and is still read.

- **A ticket's live block holds only what the agent says.** The page no longer
  gets a bullet per command, file read or edit between the agent's sentences,
  nor a line per failed tool call, nor a rule between paragraphs: only the
  prose, one paragraph after the other. The toggle's title still counts every
  step and the time spent, the `Progress` column still shows the current one,
  and the detail stays in `ponos logs -f` and the console. The three-hundred
  ceiling now counts paragraphs, so a long session no longer loses its last
  words to its tool calls.
- **A ticket's page says everything at the top, and has no tabs any more.** The
  grid always shows the type (as the board spells it: Code, Writing, External
  action, Publication), the model and the cost, beside the project, priority and
  creation date — a ticket without a model of its own shows the one
  `runner.model` gives it, marked *default*, and a cost not known yet reads "—"
  instead of hiding the cell; the duration, the pull request and the session
  follow when there are some. Under it the brief is always on screen, and *live*
  and *discussion* fold beneath it: the session is open while a run is going,
  with its green dot and its step count in the heading, and the discussion is
  counted and opens by itself when the ticket waits on you.
- **Renamed to Ponos — everywhere, not just on the cover.** The product had
  taken the name; now the rest follows: the repository is
  `SalvadorCardona/ponos`, the command is `ponos`, the Python package is
  `ponos`, the variables are `PONOS_*`, the systemd units are `ponos.timer`,
  `ponos.service` and `ponos-web.service`, the session links are `ponos://`,
  and everything on disk lives under `~/.config/ponos`, `~/.local/state/ponos`
  and `~/.local/share/ponos`. The site moves to
  [cardona.digital/ponos](https://cardona.digital/ponos/); the old address
  redirects. **Nothing is lost on the way**, and an installation moves over in
  one step:

  1. From a terminal of your own — not from a ticket, whose session runs under
     the service this stops — run `sh scripts/migrate-to-ponos.sh` from a
     checkout of this version (or simply `install.sh` again). It waits for the
     pass in progress, stops `ticket-runner.timer` and `ticket-runner-web`,
     removes their units, and installs Ponos.
  2. On its first launch, Ponos moves `~/.config/ticket-runner` and
     `~/.local/state/ticket-runner` under the new name — history, worktrees
     (git is told where they went), the Claude Code sessions filed under them,
     the console's sign-in — and says so in one line. Paths in `config.toml`
     that pointed into them are rewritten; nothing else in the file is.
  3. Rename your own `TICKET_RUNNER_*` variables to `PONOS_*` when it suits
     you: until then the old ones are read, with one warning saying which.

  The automatic update cannot cross this one on its own — the version
  installed checks a new one by importing the old package name, and refuses
  it — so it keeps running the previous version, safely, until step 1.

  **Kept for the transition, and removed in 0.3.0:** a hidden `ticket-runner`
  command that says it was renamed and runs `ponos`, the old variables, the
  move of the old directories, old `ticket-runner://` links and the console
  cookie and preferences of a browser signed in before the rename, and the
  tickets whose Runner column or reports still carry the old name — still
  recognised as this machine's. Old commits, pull requests and releases keep
  the name they were made under.

- **A blocked ticket asks a real question, in four lines at most.** The comment
  used to be the session's last sentence in one block, under the same footer
  every time — *an answer here or on your phone, yes, no, or a sentence* — and
  never said what “yes” would do. Now the session chooses the kind of answer it
  needs and the runner lays it out, one line per idea: what is done, with its
  link; why it stops, in your words; then the question — *yes / no*, a numbered
  choice of two to four options on one line, or a free question that says what
  to give. The footer and the pointer to the folded block are gone; the checks
  and the logs stay in that block. `2`, *la 2*, *la deuxième*, an option's own
  words, *oui* or a sentence are all understood, and the next run is told the
  question and the option you chose — whether you answered in Notion, from
  Telegram or Slack, or in the console. The same lines reach your phone, links
  in a comment are clickable in Notion, and it all follows `runner.language`.

- **Notion takes one band on the site, not four rows.** *Your board in
  Notion* is now a sentence and the `init` command beside a single window that
  chains the three films — his report on the ticket, a text written into it, the
  card dragged to *Validated* — under three steps you can click, each with its
  line of caption. The window opens as the band comes on screen; with reduced
  motion it waits on the board, with its play button. Notion's own *Made for
  Notion* badge, served from the site, says it works with Notion. The band is a
  third of the old height.

- **The site shows the real console right after its promise.** The section
  under the hero is *The whole loop, in four gestures*, and it is a film of the
  console itself rather than a board drawn for the page: a ticket written in
  *New ticket*, taken by Ponos with its card saying each step live, back in
  *In review* with what it cost, then validated. Light or dark as the page is,
  fetched only as the section comes near, still under its poster with a play
  button when motion is unwelcome; the four gestures under it light up as the
  film reaches them, and on a phone the film is shown larger and follows the
  card. `node scripts/film-console.mjs` films it again, on a demonstration
  board, without a Claude Code session.
- **A project's repository reads at a glance, and its brief has room.** On the
  Projects page, a card says its repository as `owner/repo` — a link to it on
  GitHub — rather than a clone URL cut after `https://github.c…`, and its
  folder by its last two parts (`…/workspace/opoil`), whole in the tooltip; the
  two facts sit one under the other so they line up. The table and a project's
  page say the repository the same way. The count at the top reads "14 of 17
  projects have a repository". The drawer a project opens in is 640px wide
  instead of 384px (still the whole screen on a phone), its first line wraps
  before the close button, and the example in "Where it is" is translated.
- **A ticket's page only says what the ticket has.** The grid under the
  status draws a fact when the ticket has a value for it: a board without a
  duration, due-date or agent column no longer shows "Took —", "Scheduled —",
  "Taken by —" on every ticket. How long a session took is read from its log
  when the board has no duration column, so a finished ticket says it. The
  priority is said once, in the grid, not again as a tag above it. The status
  reads as the board heads its column — its dot and its name with a capital —
  rather than as a coloured lower-case word that looked like a link. The header
  calls the ticket by its short id, `#a49e1a7b`, as the board does, with a
  button that copies the full one, and a long title takes a second line, its
  whole text on hover.
- **The console opens without downloading itself again.** Its files used to be
  sent whole and uncompressed on every load — 1.3 MB each time a tab was opened
  or reloaded. They are now named after what they hold, kept by the browser for
  a year and gzipped on the way out: the first load is about 410 kB, a second
  one fetches only the page, and an update is still seen on the next load, with
  no cache to clear.
- **An open console costs a fraction of what it did while tickets run.** The
  board reaches a tab whole once, when it connects, and then only as the tickets
  that changed, appeared or went: a step more on a ticket in flight is a card
  of a few hundred bytes on the stream, where it used to be the whole board —
  some 360 KB on a board of 475 tickets, about 170 MB an hour per open tab. A
  board that did not move sends nothing; only the cards that moved are drawn
  again; and a tab that missed a change, or reconnects after one, is given the
  whole board again rather than a board that drifted.
- **No click on a card starts a paid session without asking.** Sending a ticket
  back to Ready — which the next pass turns into a session — now asks first from
  every column, as "run again" already did in review: on a Validated ticket the
  dialog also says its validation is withdrawn. On Done, where almost every card
  lives, the gesture moved behind a "…" menu instead of a button on each card.
  On a Ready card, "hold → Blocked" is now **set aside**, whose tooltip says the
  runner no longer touches it.
- **The site says what Ponos is, and that Notion is optional.** Under the
  headline, one line: a harness around Claude Code that runs your tasks on your
  machine — code, writing, actions, posts. A new *What it does* section shows the
  four kinds of task, an example ticket each, then the tickets that come back on
  their own, the console's chat with your machine and projects that are only a
  name and a brief. The console is presented as Ponos's own board, over a folder
  of Markdown files. Notion, GitHub, Telegram · Slack and OpenRouter each get a
  card in *Integrations*, all optional, and Notion's films and its `init`
  command live there now. The installation shows the board as Markdown files
  first: the installer still asks for a Notion token, and Enter skips it. The
  page's description, its Open Graph card, `llms.txt` and the top of the README
  say the same.

- **The settings say what they do.** Every label, every sentence under a field
  and every section of *Settings* was rewritten in plain words, English and
  French, with its unit: *Tickets in parallel*, *Time limit per ticket
  (minutes)*, *Share kept for your own use (%)*. The sections follow what you
  are trying to do — *Running tickets*, *Models and usage*, *Repositories and
  pull requests*, *Automatic validation*, *Notifications*, *Answers in
  comments*… — instead of where a key sits in the file: the models are no
  longer spread over four of them, and the old desktop switch moved to
  *Notifications*. A choice shows what each value does (*One commit (squash)*,
  *Read only (plan)*), the key a field writes is printed under it, and the
  settings few people need fold away behind *Show the advanced settings*. No key
  changed: `config.toml` reads as it did. Two sentences that said something
  false are gone — `attach_sessions` files a session under its project for
  `claude --resume`, it does not make a link, and the board's storage mode said
  it took effect once “restart”, untranslated.

- **Ponos dresses Greek.** The antenna and its bulb are a small orange flame
  set on his head, the `>_` on his chest and the pink cheeks are gone, and he
  wears an ivory tunic with a terracotta sash and a gold brooch — on the site,
  its header, the console, the README, the favicon and the Open Graph card. The
  flame does what the bulb did: it wavers at rest, pulses while he thinks,
  burns high and flickers while he works, bounces when a ticket comes back,
  droops red when one is blocked, and is down to an ember when he sleeps. Under
  40 pixels it is one fatter orange shape, so it still reads in a browser tab.
- **A click on a project opens its form.** In the console's list of projects —
  a card, or a name in the table — the form comes up at once in a drawer over
  the list, instead of the project's page and then its *Edit* button. Escape,
  the cross or a click beside it close it; *Save* closes it and the list says
  the new name without a reload; on a phone it takes the whole screen. The
  project's page stays, one link away at the top of the drawer and behind the
  button under each card: it is where the pictures are changed and the brief
  is read as it reads.

- **The console's top bar no longer has a Ponos at its right end.** It says the
  stream, the version and the sync with Notion, then the two buttons — nothing
  else. The runner's mood is still on the mark, Ponos beside his name, at the
  top of the menu (and in the bar, on a phone).

- **The top of the site says what Ponos is.** The line under the headline
  names Notion, where the ticket is written, Claude Code, which does it on
  your machine, and what comes back — a pull request or a text, merged or
  published on your word. Beside it, where Ponos stood alone, a small picture
  plays the loop: a ticket in Notion goes *Ready*, Ponos works it with a few
  lines of his log, and pull request #96 opens — held at its end when motion
  is unwelcome, and under the text on a phone. *See it in 60 seconds* is the
  main button, the install command comes after the buttons and shows whole,
  and the line below says what it needs: Claude Code, and Notion or a folder
  of Markdown files. The count of sessions is gone from the public page.

- **The picture at the top of the site reads as the loop.** Three numbered
  steps — *Write the ticket*, *Ponos does it*, *You decide* — instead of three
  grey captions. The third is a decision: what came back fits on one line, a
  pull request or a post ready for X in turn, under the two buttons the
  console offers on a ticket in review, *Validate* and *Run again*, and an
  arrow goes from *Run again* back to Ponos — he picks it up with your note.
  Ponos's log is one line anyone can read, *Working on it…* then *Done*, and
  the ticket of the first step stays *Ready*. Without motion, the picture rests
  on the decision, both buttons on show.

### Fixed

- **The cost of a blocked or failed session is now written in Cost.** Only finished tickets
  recorded theirs, so those sessions were missing from the board, the history and the
  statistics.

- **A forced merge that is only late no longer sticks in review.** With
  `force_validated_code`, a pull request overtaken while its CI ran — behind
  its base or in conflict with it, as two tickets on one repository do to each
  other — or whose CI is still running when `checks_timeout_minutes` runs out
  now goes to *Validated* instead of *In review*: the next pass replays it,
  resolves its conflict if it has one, and merges it, with nobody moving it and
  no session's place held while it waits. Its report and card say the merge was
  postponed and why (⏸️ *Waiting*). A check red on this pull request only, or a
  refusal about a review or the branch's rules, still waits in review; so does
  everything on a board with no *Validated* column.
- **The e2e of a ticket's discussion no longer fails when it runs while the gestures e2e has a ticket set aside**: it looks for the mark on the card of the ticket that asked a question, instead of counting every Blocked card on the shared board.
- **A queue of validated pull requests no longer blocks itself.** Ten pull
  requests validated on one repository move its base on their own: each merge
  leaves the others behind — and conflicting, when they all touch the
  changelog or the console's built files — so the third or fourth in line was
  replayed twice and blocked as "`main` keeps moving faster than its pull
  request can be replayed onto it" (three tickets in five minutes on
  01/10/2026). A replay is no longer held against a ticket when the runner
  itself merged into that repository since the ticket's last replay: its count
  starts again. A base moved by anyone else still stops after two replays.

- **The console's browser tests pass again, in parallel, and two at a time.**
  For anyone changing the console: `npm run test:e2e` gives the chat tests a
  server of their own, so a turn they leave running no longer meets the
  shortcut tests' Escape, and both servers take free ports
  (`TICKET_RUNNER_E2E_PORT` pins them) — two worktrees no longer fight over
  8790. CI also runs them when only the console's server changed.
- **A session no longer kills itself with `pkill -f`.** The prompt went on
  `claude`'s command line, and it holds the ticket's page — the last run's
  trace included. A ticket that quoted `vite --port 5199` had its session run
  `pkill -f "vite --port 5199"`, match its own command line, and die with exit
  code 137; other sessions carrying the same words could go with it. The
  prompt now always reaches the session on its standard input, never as an
  argument, so `ps` shows nothing of a brief to the other users of the machine
  either. The instructions of a code ticket also ask to stop a server by its
  PID or its port (`fuser -k 5199/tcp`) rather than by a pattern.

- **A ticket opens at once.** Its page stayed empty two to five seconds while
  the console read the whole ticket from Notion — and read it two or three
  times per opening. The title, the column, the project and the cost are drawn
  straight from the board, and only the brief waits, read once per opening.
  The console also keeps a ticket's page while its `last_edited_time` holds:
  opening it again costs one Notion request instead of one per block, and a
  brief edited in Notion is read again at the next opening.
- **A red CI no longer blocks a ticket for what is not its fault.** Once a
  pull request's conflicts were resolved, the slightest red check sent the
  ticket to *Blocked* with nothing but “CI: red.” — a flaky end-to-end test or
  a `main` already red was enough, and every ticket merged at that moment
  stopped on it. The failed GitHub Actions jobs are now run again once before
  anything is concluded, and a check still red is compared with the newest
  commit of the base branch: red there too, it was inherited, and the pull
  request is merged all the same, its report saying which check and why. Only
  a check red here and not on the base still blocks — and the report names it.
  The same reading applies to a type whose validation is forced.
- **A pass started during an update no longer dies on a mixture of two
  versions.** The update rewrote the installation in place, and a pass the
  timer started at that moment imported some files already new and others
  still old — `ImportError: cannot import name 'SLOTS'`, and the service marked
  failed. Each version is now installed in a directory of its own
  (`app-<commit>`), checked there, and `app` is switched onto it in one step;
  the launcher reads the link once when it starts, so a pass runs whole on one
  version, and the previous one stays on disk for going back. `install.sh`
  installs the same way; an existing installation is moved to it by its next
  update.
- **Amounts, numbers and plurals are written in the console's language.** The
  same cost read "$1.36" on a card, "2724.82 $" in the strip at the top and
  "$2627" in the statistics, and a count had no thousands separator or said
  "6 ticket(s)". In French the console now writes « 2 734,75 $ », « 1 178 »
  and « 1 ticket » / « 6 tickets » ; in English "$2,734.75", "1,178" and
  "6 tickets" — no "(s)" left anywhere.

- **The console fits a phone.** The bar along the bottom held six pages in a
  row wider than the screen, scrolling sideways without saying so —
  *Statistics* cut in two, *Settings* out of sight. It now holds the board,
  the projects, the schedules and **More**, which opens the other three, and
  fits a 360px screen. At the top, the two green dots without a word and the
  missing version are one pill, *live*, that a tap opens on the stream, the
  last read of Notion and the version. The bubble no longer sits over the end
  of a page — a card's link, a token's *forget*, the top of a chart — and a
  section's *Save* is no longer hidden behind the bottom bar. The settings
  lose the blank band over their tabs, which also covered the section's name,
  and a list's icon lines up with its name rather than with its sentence.

- **A tab closed mid-request no longer fills the console's journal.** Closing
  or reloading the console while it was answering left two Python tracebacks
  in `journalctl` each time — the broken pipe, then the 500 the console tried
  to write on the same closed connection — and they hid the real errors. A
  client that has gone is now let go in silence; a route that fails still
  answers 500 with its message.
- **A picture in a Notion brief shows on the ticket's page.** A capture
  pasted into a ticket came out on the console as a bracketed English sentence
  ending in an S3 address cut off its signature — a link that answered 403.
  The page now draws the picture with its caption, and a click opens it full
  size; a file or a PDF is a link that opens, and the console says it in its
  own language. What the session reads still names the file, by its caption
  or its name, without the dead address.

- **The console in French no longer slips into English.** The pages of a long
  list say « Affichage de 1 à 30 sur 475 résultats », with a single ellipsis
  between the page numbers instead of four dots; a ticket Notion has no title
  for is « (ticket sans titre) »; and the *By status* card of the statistics
  names the columns as the board does — « Done », not « done ».
- **The schedules list no longer shows a next date in the past.** A schedule
  turned off said *paused* instead of the date the last pass left on it — weeks
  old, for a row that will not fire — and one that is on and due shows the current minute,
  since it fires on the next pass. The cadence is drawn in the console's
  language (*Toutes les heures*, *Quotidienne*…) while the board keeps
  `Hourly`; the count reads *1 active sur 2*; and on a phone the table keeps
  the name, the cadence, the switch, the next date and the edit pencil on the
  screen, the other columns being a tap away in the form.

- **Markdown in the console reads as text, not as its source.** A numbered
  list is counted — 1, 2, 3 — even when it was written « 1. 1. 1. », as every
  Notion brief is, and a list that starts at 3 still starts at 3; a table is
  drawn as a table, with its head, and scrolls sideways when it is wider than
  the screen; a bold or an italic may hold a bit of code or a link without its
  asterisks showing. In a ticket's brief and in the workspace's chat alike.
- **The way back to the settings leads to the settings.** "Settings" in the
  bar's breadcrumb, and an address such as `/?view=console/settings` typed by
  hand, opened a page that said "Something went wrong" and nothing else; they
  now open the settings. The top of the page says what it is once — no more
  "← Settings", a second title and "#config" over "Configure the runner."
- **Tickets abandoned on a board without a Runner column come back.** The
  runner signs a ticket it claims in that column, and only put back the ones
  it had signed — so on a board without it, a ticket left *in progress* by a
  reboot or a crash stayed there for good. Without the column, every ticket
  in progress that no run is holding goes back to *Ready* (one machine per
  board, then); with it, nothing changes, and another machine's tickets are
  still left alone.

- **A missing column is said, not swallowed.** `ticket-runner doctor` checks
  every column the runner works with — the optional ones too — and counts as
  a problem each one that is missing or of the wrong type, with what it
  switches off; `ticket-runner init` adds them. And a run that writes to a
  column the board does not have says so once, instead of dropping the value
  without a word.

- **An update that does not start is taken back.** A version is started by a
  Python of its own before it is kept; if it fails to import, or its launcher
  and units cannot be written, the installation returns to the commit it
  replaced instead of leaving a runner that dies before its first ticket.

- **The version no longer shows ↑ for an update already installed.** The check
  was written before the update it announced and read for the hour after; the
  header now compares it with what is actually on disk.

- **Every page of the console scrolls again.** Since the console moved to the
  admin layout, a page taller than the screen — a ticket and its session log,
  the settings, a long board — stopped at its bottom edge: no wheel, no
  touchpad, no scroll bar, no Page Down. The page scrolls as a whole now, under
  a bar and a menu that stay where they are; a dialog still holds it still
  while it is open, and lets it go when it closes. `npm run test:e2e` in
  `frontend/` checks it in a browser.

- **Blocked tickets were missing from the console on a board where `failed` and
  `blocked` are one status.** The console drew one column for both, the first,
  and put the tickets in the second — three tickets blocked in Notion, none on
  the console. A status now lands in the first column that carries it.

- **A run no longer writes its verdict over a status you changed by hand.** The
  page is read again before a status is written; a ticket moved during the
  session keeps your column, the run says so in its log and in the journal, and
  the console marks the card.

- **The Markdown mirror no longer loses the second edit of a Notion minute.**
  Its stamps carry a fingerprint of the page's properties, not only an edit
  time Notion rounds to the minute.

- **The console no longer drags on a board with years of Done.** The Done
  column draws its thirty most recent tickets and a *Show more* button under
  them; its heading still counts every one. The projects page no longer reads
  the whole tickets database to count what each project holds — the console
  counts the tickets it already has — and the schedules page draws its rows
  without waiting for the list of projects. `node scripts/measure-console.mjs`
  times it on a board of 350 tickets.

- **What an audit found, closed.** A `ticket-runner://` link could hand ssh an
  option (`?host=-oProxyCommand=…`): the host and the session id are now checked
  and ssh gets the host after `--`. The console no longer offers `run`, `update`
  or `clean`, and a command that outlives its three minutes takes its whole
  process group with it. `clean --force` takes the run lock and never acts on a
  repository that does not list the directory as its worktree. The run lock is
  never deleted nor emptied before it is held; the state files are written
  whole; the console's token, the copies of the configuration, the session logs
  and the history are created private. Notion reads that time out are retried
  and end as a Notion error, a `429` waits what it is told, and a write that may
  have landed is never sent twice. A ticket that raises fails on its own instead
  of ending the pass, and a git command past its timeout is a failed command. A
  prompt too long for one argument reaches the session on stdin. And `serve`
  starts on a fresh installation, token or not, as its first connection promised.

- **Telegram and Slack can listen to named people only.** `allowed_users` in
  `[notify.telegram]` and `[notify.slack]`; empty keeps the old behaviour, and
  `ticket-runner doctor` warns about a group or a channel where anybody can
  answer — an answer can wake a ticket.

- **An update puts the console on the code it just installed.** A run is a
  process that ends, so the version that lands between two passes is the version
  the next pass runs. The console is not: it is started once and answers for
  weeks, with the Python it was given at boot — while serving the page off the
  disk, which the update has just replaced. The two drifted apart, and the
  browser is where it showed: a console up since the evening before drew the
  project list, and opening a project answered `no such route:
  /api/projects/<id>` — the page was the morning's, the server it asked was the
  day before's, and all the page said was that the project could not be read. An
  update now restarts the console onto the code it installed, and never starts
  one somebody had stopped.

- **A project that cannot be read says what the server answered.** The page had
  one sentence for every failure, which made a route that had moved and a
  project that is gone look the same. What the server said is under it now, in
  its own words.

- **A ticket's page says how long the run took, and which machine took it.** The
  runner has always written both back to the board, and the console drew
  neither: a ticket home from a session said what it had cost and never how long
  it had taken, and a board two machines share never said which of them had the
  ticket in hand. Both are on the page now, beside the spend, and the *took*
  column is in the table layout of the board — where it is read in words rather
  than in minutes: `23 min`, `1 h 02`.

- **A board that is not Notion's stops offering links to Notion.** On a Markdown
  board a ticket's page is a file on this disk, and every card carried an
  outward link pointing at it with `file://` — an address a browser declines to
  follow from a console served over HTTP, without saying so. The link is offered
  where it leads somewhere, as a project's already was. The board no longer
  opens on "Notion holds the board" either, the live pane no longer says there
  is "no Notion in the way", and a form that saves says *Written* rather than
  *Written to Notion* — the same toast answers a project written to Notion, a
  project written to a file, and a setting written to `config.toml`.

- **A row of the board's table layout opens its ticket.** The table drew eight
  columns and offered no way into any of them: a ticket picked out there had to
  be found again on the cards. Every row now has the same *open* the projects
  have.

- **The board comes back in the layout you left it in.** What was fixed for the
  projects was true of the board too — the *table* you switched to was gone on
  the next reload and gone again on the way back from a ticket. It is in the
  address now, and the links back to the board carry it.

- **A pane stops printing where you are twice.** The bar above every pane says
  the path; Live, Schedules, Context and Settings each said it again on the line
  under it.

- **A ticket's discussion opens at its first comment.** Three comments opened
  with the first one cut in half and a screen of nothing under the last: what
  you had written was pinned to the top of the scroller, which is what a live
  conversation wants and not what a discussion read oldest-first is.

- **A brief written by hand reads as prose.** A paragraph wrapped over three
  lines — which is what a Markdown board holds, and what anybody typing into a
  ticket writes — was drawn as three paragraphs with a gap between each. Lines
  under one another are one paragraph again; a blank line is what ends one.

- **An empty board says so, in the language the console is in.** It said "No
  results yet — nothing matched your search", in English, on a page where nobody
  had searched for anything.

- **A date on the board is a date.** A ticket scheduled for a day showed
  `2026-09-19T00:00+02:00` on its card, on its page and in the table, beside an
  "il y a 7 h" written like a human. It now reads `19 sept. 2026`, and a
  scheduled hour is kept where there is one.

- **A link to a pane opened with the console's token lands on that pane.** The
  token is moved out of the address and into a cookie as soon as it arrives, so
  it does not sit in the history and in every screenshot — but everything beside
  it went with it, and `/?token=…&view=console/projects/list` opened on the
  board. What was carried is now carried back, the token excepted: a link to the
  projects, to a ticket, to one section of the settings is a link you can send
  to yourself with the token on it.

- **The projects come back in the layout you left them in.** The two layouts of
  the Projects screen — cards and table — moved on screen and nowhere else: a
  reload, or the way back from a project, put you on the cards whichever one you
  had picked. The layout is in the address now, and the links back to the list
  carry it.

- **The brief of a project stops asking for a message.** The empty box under
  *The brief* offered “Votre message…”, which is what a chat box says and not
  what the field is: a page of standing instructions every ticket of that
  project is told before it is told the ticket. The repository and the path on
  this machine are cut to the width of a card rather than shown whole, and are
  now readable in full by resting on them.

- **A project on a Markdown board no longer offers a link to Notion.** Its page
  is a file on this disk, and the page's outward link pointed at it with
  `file://` — an address a browser declines to follow from a console served over
  HTTP, without saying so. The link is offered where it leads somewhere.

- **A branch is replayed on a machine that has no git identity of its own.** A
  rebase writes commits, and git refuses to write one where it cannot tell who
  is writing — a CI runner, a container, a server nobody ever configured. The
  replay failed there on that, the failure read as the branch refusing to move,
  and the ticket landed in Blocked saying the pull request would not merge:
  true, and not the reason. The runner now lends git an identity where it finds
  none, and leaves alone the machine that has one — the replay of your own
  branch is still committed under your name.

### Changed

- **The product is called Ponos.** The robot gave it his name: the site, the
  README, the console's sidebar and tab, the messages on Telegram and Slack,
  the desktop notifications and the words `ticket-runner doctor` and the
  welcome screen print all say Ponos, and the site opens on a one-minute video
  of a ticket going from *Ready* to *Done*. Nothing to change on your side:
  the command, the Python package, the repository, the configuration and state
  paths, the `TICKET_RUNNER_*` variables, the systemd units and the
  `ticket-runner://` links keep the name they were installed under.
- **The robot has a name — Ponos — and the site looks like the console.**
  Ponos, after the Greek god of toil, is the one who does the tedious part:
  the console says so when you hover him (*Ponos is taking a ticket*, *Ponos
  prend un ticket*), and the site opens on him and on one promise — *Write the
  ticket. It comes back done.* The site now tells the loop in six sections
  instead of seventeen, and everything it used to explain lives in the README,
  which opens the same way. It takes its colours, faces and radius from the
  console's own tokens, in light and in dark, with a switch; the command, the
  package and the repository keep the name ticket-runner.

- **The robot is cuter, and still reads at 24 pixels.** A big round head on a
  small round body, stubby arms and legs, big eyes with lights in them, pink
  cheeks and a mouth; softer colours, with a gloss and a soft shadow. Every
  state has its face — a pout and a tear when a ticket is blocked, a snoring
  mouth asleep, an open smile on a hop that squashes when it lands. Under 40
  pixels — a card, a toast, the bar, the favicon — it is only its face, drawn
  larger. `--robot-cheek` and `--robot-glint` join the colour variables; see
  [Mascot](CONTRIBUTING.md#mascot).
- **The console is drawn in react-resource-view's admin layout.** The menu, the
  bar and the page's heading are the package's own now, around the same pages:
  the board, a ticket, *Live*, the projects, the schedules, the context and the
  settings. On a phone the menu runs along the bottom edge. The stream's dot,
  the version, *Refresh* and the light moved from the foot of the menu to the
  end of the bar; the menu no longer folds to a rail of icons. The old
  `/?page=live` and `/?page=context` addresses still land where they did, and
  the board follows the stream again without a reload — a card moved from
  another tab or from Notion now moves on the one you are looking at.

- **An installation updates to releases, not to every commit of `main`.** The
  runner followed the branch it was installed from, so anything merged into
  `main` was running everywhere within the hour, before anybody had called it a
  version. It now follows the newest `vX.Y.Z` tag, updates nothing while there
  is none — and says so in the journal — and never takes an installation that is
  already ahead of the tag back to it. `runner.update_channel = "main"` keeps the
  old behaviour; `ticket-runner doctor` says which one is followed.

- **The bar says where you are, and the discussion opens from a bubble.** The
  top of every page carried a row of pills — the timer and its interval, a run
  in flight, how many tickets had been handled and for how many dollars, a
  version waiting — and the language the console reads in. All of it was true
  and none of it was worth the room: a state you cannot act on, repeated over
  every page, is noise with a border around it. The bar is now the path and
  nothing else. What a run is doing is what *Live* is for; the version, and the
  day a newer one is waiting, sit at the foot of the menu beside the stream's
  own dot; and the language moved to *Settings → This console*, which is where
  somebody looking for a setting looks — it is still this browser's alone and
  never reaches `config.toml`. The conversation moved with it: instead of a
  second column taking half the screen whether or not there was anything in it,
  an entry in the menu to reach it on a phone and a switch in the bar to fold
  it away, there is **a bubble in the bottom corner** that opens a drawer over
  the page — the ticket's discussion when a ticket is open, the workspace's own
  everywhere else. The page keeps its full width until you ask for it.

- **Schedules is a list and a calendar, and a row is turned off from the list
  itself.** The page was drawn by hand — its own cards, its own form, its own
  way of writing "in 6 days" — on a console whose board, projects and settings
  are all drawn by the view package. It is now a resource like them, in the two
  layouts that page actually wants. *Table* compares them, and `Active` is the
  one cell you can type in: **unticking a row in the list stops it**, with no
  form to open and nothing deleted, which is the gesture this whole feature was
  built around. *Calendar* answers the only question a schedule really has —
  when the next one lands — by laying the occurrences out over a day, a week or
  a month, in your language and starting the week where your language does;
  clicking one says what it will make. *New schedule* and the pencil on a row
  write the six columns a schedule is written in, and still never `Next`,
  `Last` or the ticket the last occurrence made: those are what a pass writes
  back. `/?page=schedules` keeps working and lands on the list.

- **The menu is a name and a count.** Each of the seven entries carried a
  sentence under its name — how many tickets were ready, how many turns the
  conversation had, whether the timer was on — so a menu of seven addresses was
  fourteen lines to read, saying in the smaller type what each page says at the
  top of itself. An entry is now its name, and a number beside it where
  something is waiting there: the tickets on the board, the sessions writing
  right now. The timer is on the *Live* page, which is the page about what the
  runner is doing.

- **The settings are a page per section, and a link you can send.** The Settings
  tab was one column of collapsibles that drew all seventy fields at once, open
  or folded, and redrew every one of them at every keystroke. `config.toml` is
  now a resource with a single record, and each section of the file is a
  sub-page of it: the tab you are on is in the address, so
  `/?view=console/settings/read/config/notify` is a link to the notification
  settings that opens where you left it. Only the section you are looking at is
  drawn; what you typed in one you left is kept and given back when you come
  back to it. The tabs are built from what the server says the file holds, so a
  section the runner gains is a sub-page the day it is described. `[projects]`
  and `[github]` — the two mappings you add rows to rather than fields you fill
  — are tables of their own under that page, with the "add" dialog and the
  confirmation before a row goes, which retires the one hand-rolled table of
  inputs the console still had.

- **What a session says in the console is read, not parsed.** Both transcripts —
  the workspace's and a ticket's — showed a message exactly as it was written,
  so an answer arrived as its own source: `##` in front of the headings,
  asterisks around the emphasised words, a fence around the command it wanted
  you to run. They now draw the markdown they are handed: headings, lists
  nested as deep as they were written, the boxes a checklist ticks, quotes,
  fenced code, and a word behind a link. The surface it is said on is
  shadcn/ui's own chat bubble rather than one this console styled by hand, so a
  problem still reads red, the workspace still reads as a card, and your own
  turns still carry the accent. A ticket's page, which was already drawn this
  way, gains the same additions.

- **A report is a notification now, and it is three lines long.** The comment
  the runner writes under a ticket *is* what Notion pushes to your phone, cut
  after two or three lines — and it used to spend its first forty-four
  characters on `ticket-runner@salva-Inspiron-16-Plus-7620 — ` and the five
  after that on `done.`, so the notification stopped roughly where the
  information began. It now opens on a mark and a verdict that says what is
  expected of you — **To review**, **To read**, **Stuck**, **Failed**,
  **Waiting**, **Merged**, **Published** — followed by the figures that place
  it: `✅ To review — PR #12 · 3 commits · 18 minutes · $1.20`. Under it, one
  sentence, cut at two hundred characters whatever the session wrote, and the
  link on its own line. A blocked ticket puts the **question** on that first
  line, because that is the thing to read. Nothing is lost: which machine ran
  it was always in the board's *Runner* column, the session is a click in its
  *Session* column, and the command that resumes it — with the log path and the
  worktree kept — is folded into the block the run already writes its steps
  into, which on a failed run is renamed `⚠️ Trace` and is the only place it
  appears. On a run that went right it appears nowhere, because nobody has ever
  needed to resume a session that finished. The desktop notification and the
  Telegram or Slack message now say the same words as the comment rather than
  words of their own, and the folded block's title follows `runner.language`
  like everything else. Two things the runner used to recognise itself by the
  signature — a ticket that wakes on your answer, and the console's
  reading of a discussion — read the mark instead, and the reports already on
  your board keep being recognised by their old signature.
- **A pass fills its free places as they free, instead of running a batch and
  waiting.** `max_concurrent` used to be the size of the first handful: the
  tickets that happened to be ready at the pass's first second were prepared,
  and the pass then waited for every one of them before ending — so a ticket
  made ready at 14:10 waited for the two-hour session that started at 14:04,
  and for the timer after it, however many places were sitting empty. Measured
  on a real board: a pass with two tickets, one done in minutes and one still
  running twenty minutes later, while four tickets reached the ready column and
  not one agent was started. `max_concurrent` is now a number of **places**: a
  session that ends frees one, the board is read again on the spot, and the
  ticket that goes in is whichever is top of the queue *then* — same priority,
  date and age order as at the start. The pass ends when nothing is ready and
  nothing is in flight, and each ticket is written into `ticket-runner history`
  as it finishes rather than at the end. Nothing changed about the run lock or
  the timer: it is the pass that became continuous, not the number of runs. Two
  consequences worth knowing — `ticket-runner run --limit 3` means three
  tickets for that pass, not three at a time; and a comment *addressed* to the
  runner during a long pass is still answered by the next pass, because
  answering starts a session of its own, while an answer to a blocked ticket —
  typed in Notion, Telegram or Slack — is picked up by the pass itself at the
  next freed place.
- **A place nothing ever took is filled too, and that is what makes
  `max_concurrent = 2` mean two.** Filling a place when a session *ended* left
  the ordinary case out: tickets arrive one at a time, so the first one starts,
  the second place stays empty, and the pass then had nothing to do but wait for
  the session in flight before reading the board again. Nobody else could read
  it either — the run lock is the pass's until it ends, and the timer that fires
  every interval meets it and leaves — so one ticket in progress meant one
  ticket at a time, however many places you had allowed. A pass now looks at the
  board for as long as it holds an empty place, every `interval_seconds`: the
  same cadence the timer reads it on, so a board watched every ten seconds
  starts a second ticket within ten seconds of it being made ready, and one
  watched every half hour behaves exactly as if the runner had been idle.
  Nothing else moved — a full pool still asks the ready column for nothing and
  costs it not one extra request, `--limit` still caps the pass and not the
  width, and a spent subscription still stops the pass from starting anything at
  all.
- **A ticket you validate is carried out at once, and not when the sessions in
  flight are over.** The *Validated* column was settled at the top of a pass and
  never looked at again, so everything accepted while the pass ran waited for
  it: a pull request validated at 14:20 was merged when the two-hour session
  started at 14:04 ended — and on a board where something is nearly always in
  progress, that is a column of finished work standing still behind work that
  has nothing to do with it. A pass now reads that column for as long as it
  lasts, every `interval_seconds`, **whether or not a place is free**: a merge
  costs no place at all — two `gh` calls in the pass's own thread — so it
  happens at 14:20 even with every session running, and a publication, which is
  a session, takes the next place that frees, ahead of the ready column. What is
  in progress goes on being in progress: nothing is interrupted, no session is
  started beyond `max_concurrent`, and a validated ticket taken by the pass is
  held out of the next reading so that nothing is ever published twice.
  `--limit` counts tickets off the ready column and has never counted these.
- The web console has been redrawn. Every page opens the same way — where you
  are, said as a path; a heading you can read from across the room; and the one
  line that says what the page is for — and the accent is a lime, so the button
  worth pressing is the only thing on the screen wearing it. A ticket's card
  says its id and its age before it says anything else, and states its project
  and its cost along the bottom; a ticket's page states its metadata as a ruled
  grid instead of a row of pills. Sessions open on the three numbers you came
  for: how many are writing, how often the timer comes round, what has been
  spent.
- Forms read as forms. Every field the console draws — its own on the settings
  tab, and the ones react-data-form builds for a new ticket — sits in a filled
  box with its label against it and its explanation under it. The settings tab
  gains a list of its sections down the left, which says what the file holds,
  which parts are open, and how many of your unsaved changes are hiding in a
  part you folded away; a field you have touched says so.
- Reports read like sentences rather than like a row of fields. What used to be
  `Branch \`x\` · 3 commit(s) · <url>` followed by three lines of session
  machinery is now “3 commits on \`x\`, and the pull request is waiting to be
  read: <url>”, a line saying what the run took and cost, and the resume command
  last — where you look on the rare day something went wrong, rather than first.
  Durations are rounded to the minute, prices to the cent.
- The web console's board is now the board: the columns your Notion board has,
  under its own names, and a card dragged into one moves the ticket. The
  *table* tab shows the same tickets as rows. A new ticket is written in a form
  over the board rather than in a strip above it.
- A card opens a page of its own — the brief, the report a run appended, the
  notes in between, read from the Notion page — with the ticket's terminal
  beside it, in place of the workspace console. The *Ticket* entry of the menu
  is gone: the page is where the card takes you, and it has an address
  (`/?view=console/tickets/read/<id>`) a reload or a link comes back to. Every
  page does — `/?page=live`, `/?page=settings`.
- The board, the ticket page and the form are one declaration for
  [react-resource-view](https://github.com/SalvadorCardona/react-resource-view)
  and [react-data-form](https://github.com/hermez-agency/react-data-form);
  the two transcripts are shadcn's `message` and `message-scroller`. A switch at
  the right of the header folds the second column away, for a board that wants
  the width.
- The board opens on one heading instead of two, and a new ticket is written in
  a panel. react-resource-view 0.7.0 draws a list's header itself — the board's
  icon, its name and the line that says what it is for, with the *board* and
  *table* switch and **New ticket** on the same row — so the console has given
  up writing its own above it. The form for a new ticket slides in from the
  right of the screen, and up from the bottom on a phone, rather than landing in
  a dialog in the middle of it: a brief is written at full height with the board
  still there behind it, and the panel closes itself once the ticket is written.
- `doctor` says how the console is opened. “We set up a sign-in and the page
  still asks for a token” had no answer anywhere but in the configuration file:
  the sign-in only exists once `web.email` *and* `web.password` are both set,
  and the token never goes away in any case — it stays what a script and
  `serve --print-token` carry. A *Console* section now names the address and
  which of the two doors it opens on, and calls out half a sign-in — an email
  without a password, which is not a way in — where the only sign of it used to
  be a login page that never appeared.

### Added

- Tickets that come back on their own. A fifth database, *Schedules*, where one
  row describes a ticket and how often it is born — `Cadence` (Hourly, Daily,
  Weekly, Monthly), `At`, `Day`, and the `Active` tick that turns it on — with
  the body of its page as the brief, copied into every ticket it makes. When the
  moment comes, the runner writes the ticket into the ready column and steps
  back: same column, same queue, same session, same pull request. Monday's
  dependency review is written once instead of being retyped every Monday.
  Two rules are the whole point of it: **catching up creates one occurrence, not
  the missed ones** — a machine off for three days wakes up owing one ticket and
  not twelve — and **an occurrence still open blocks the next one**, so a
  schedule stuck on a question does not fill the board with copies of itself.
  `ticket-runner init` builds the database, on a bare page or on a board that
  predates it; `ticket-runner schedules` says what repeats and when it next
  does; `ticket-runner schedules --run "<name>"` makes its ticket on the spot;
  `ticket-runner list` now shows the whole calendar, the tickets waiting for a
  date and the ones not written yet. Optional throughout: a workspace with no
  schedules page has nothing that repeats, `doctor` is green on it, and
  `runner.schedule = false` turns everything off without a row being unticked.
- The web console shows what comes back on its own. A *Schedules* page in the
  menu — `/?page=schedules` — reads the calendar the way `ticket-runner
  schedules` reads it: what repeats, at what rhythm, when the next ticket is due
  and when the last one was made, with a way through to the ticket that
  occurrence produced. A row nobody can read says what is wrong with it rather
  than showing a date it does not have, and `runner.schedule = false` is said at
  the foot of the page — a browser was the one place that switch could not be
  seen, and a calendar of ticked rows that never fire reads as one that works.
  Nothing is written from here: a schedule is a Notion page, and its name is the
  link to it. The page asks Notion when you open it rather than living on the
  event stream, so a tab left open on the board never polls that database.
- `GET /api/tickets/<id>`: one ticket, with the page under it flattened the way
  the runner reads it before a run.
- `GET /api/schedules`: the Schedules database as the console draws it, with
  what makes each row unreadable spelled out rather than raised.
- The official `shadcn` skill, vendored under `.claude/skills/shadcn`, so a
  session working on the console composes from the same kit.

### Fixed

- A project whose `Path` points nowhere is no longer refused when the same page still
  names its repository. Rename a clone on disk and the page keeps the old path, while
  its `Repository` column stays right — the runner used to stop at the first wrong
  declaration and never read the second, blocking every ticket of that project with
  `project not found on disk`. Each way is now tried in turn, and the ticket runs on
  what the first working one finds; its comment says which declaration is out of
  date, and `ticket-runner projects` shows the project with a `!` rather than a tick
  until you correct it. A repository renamed on GitHub is found too: `gh` is asked what
  the old name is called now, and that is what the clones are matched against. What a
  fallback may find is deliberately narrow — only a clone whose `origin` remote is the
  one declared, never one whose folder is merely named like the project, and never one
  of two clones that answer to the same remote. A project none of its declarations lead
  to is still put back, and the comment now lists every way that was tried and why each
  one failed, instead of the first disappointment alone.

- A desktop notification now takes you to the ticket it names: clicking it
  opens that ticket's Notion page, where before a click did nothing and you
  had to go and find the title on the board. `notify-send` cannot do it — it
  never hands back the identifier a desktop answers a click with, and on GNOME
  it refuses `--action` outright — so a notification with a page behind it is
  posted over D-Bus and followed by a detached process, which waits for the
  click and then goes quiet. A machine missing `gdbus`, `dbus-monitor` or
  `xdg-open`, or a desktop that does not do notification actions, gets exactly
  the notification it got before.
- `ticket-runner init` can build the Tickets database on a bare page again. It
  declared the *Project* and *Agent* relations in a shape the Notion API
  rejects, so on 8 September 2026 a fresh page stopped at `POST /databases:
  400 body failed validation. Fix one:` — and said nothing after the colon,
  since only the first line of the error was shown, then claimed nothing was
  half-built when the workspace and the Projects and Agents databases already
  were. The relations are now spelled the way the API accepts; when the API
  refuses something, `init` prints every line of its answer; and the advice
  says what is true: what was built is kept, run the same command again.
- The runner no longer goes quiet after a run that failed. On 7 September 2026
  a Notion timeout failed a run, the timer was restarted, and nothing ran for
  the next two hours: the timer counted from the boot and from the service's
  last activation, had neither to count from, and sat *enabled* with no next
  run — `status` showed a green tick the whole time. The timer now also counts
  from its own start (`OnActiveSec`), so it always has a next run. `status` and
  `doctor` read that next run rather than `is-enabled`, and a timer that has
  none is a red line, not a tick; the console's badge says *stalled*. And
  `status` no longer reports a run in progress on the strength of a `run.lock`
  a dead process left behind: it asks the lock itself, which the kernel drops
  with the process. **An existing installation keeps its old unit, and the fault
  with it, until `ticket-runner enable` is run again** — which now restarts the
  timer rather than leaving an active one as it was, since a reload alone does
  not revive a starved timer.
- A ticket that has run before is picked up instead of being refused. Its branch
  is named after it, so a session that failed, or a pull request nobody merged,
  left a branch that answered `branch ticket/… already exists — ticket already
  handled?` on every pass afterwards — the ticket was stuck until somebody ran
  `ticket-runner clean --force` by hand. That branch is now checked out again,
  replayed on top of the newest base, and the session carries on from what it
  already holds: the agent is told it is continuing somebody's work, the ticket's
  comment says what was reused and what it was rebased onto, and the push that
  follows forces with a lease, since the history under it was replayed. A rebase
  that conflicts is undone rather than left half-applied — the session still runs,
  and the conflict is a line in the comment. Two things still stop the ticket, and
  both should: a branch another worktree has checked out, and a directory holding
  commits or changes that were never anywhere else.

### Added

- A date on a **validated** ticket is honoured too, so the board schedules what is
  finished and not only what is to be done: the post you wrote on Monday and accepted on
  Tuesday goes out on Thursday at 18:00, on its own, rather than on the pass that follows
  your click. The ticket waits in its column until the moment comes, and a pull request
  waits the same way — one column, one rule. `ticket-runner list` shows what *Validated*
  is holding back beside the ready tickets waiting for their date, and a pass counts them
  both.

- A ticket nobody got round to titling is named by the runner when it becomes
  ready: a very short session reads what the page says and writes a title back
  into Notion, so the board shows it too — and the branch reads
  `ticket/retirer-le-shader-…` instead of one more `untitled-ticket`. A ticket
  that already has a title keeps it and costs nothing extra, and one with
  nothing on the page still comes back with the question rather than a name
  invented for it.
- A terminal for one ticket, in the console: click a card and the **Ticket** tab

- The console is a React application. Its page is rebuilt on TypeScript, Vite,
  Tailwind and [shadcn/ui](https://ui.shadcn.com), and it has a light theme now —
  a switch in the header, dark still what it opens on. Nothing about how it is
  installed or served changed: what ships is the built bundle, committed beside
  the Python that serves it, so a machine still needs `python3` and `git` and no
  Node at all. Its source lives in `frontend/`.
- A menu down the left of the console, in place of the row of tabs — and it says
  more than the tabs could: how many tickets are ready and how many are in
  review, which ticket the Ticket pane is holding, how many sessions are writing
  right now. `Ctrl-B` folds it to a rail of icons; on a phone it is a drawer.
- The repository declares the shadcn MCP server in `.mcp.json`, so an agent
  working here can search the registry and add a component without leaving the
  session.
- A terminal for one ticket, in the console: click a card and the **Ticket** pane

  shows everything said on it — the runner's reports, your answers, the ones you
  gave from Telegram — with a field to say the next thing and, while it runs, its
  session's steps scrolling underneath. What you type is a comment on the ticket,
  written into the thread the runner last spoke in: answering its question runs
  the ticket again, and naming it asks it for words instead.
- Addresses in the console are links. An answer, the output of a command, a step
  of a session or a comment on a ticket that carries a URL is one click away,
  rather than something to read out loud into another tab.
- A ticket moved to *Ready* becomes a Claude Code session: a disposable git
  worktree, a branch, commits, and a pull request — or, for a project with no
  repository, a document written back into the Notion page itself.
- A projects database, a context page and an agents database, so a ticket knows
  which repository it belongs to, who the work is for, and who handles it.
- A discussion on a ticket: a comment under one of the runner's reports is
  answered in the thread by something that has read the ticket and the code.
- Telegram and Slack: a ticket the agent will not guess at asks its question
  where you already are, and one word answers it.
- `ticket-runner serve` — the web console: the board live, the CLI in a browser,
  and a chat with the whole workspace.
- Progress written as the session runs, at a ten-second cadence: a bullet per
  command run and per file touched, and what the agent says as a paragraph of
  its own — whole, in its own markdown, and never cut to the length of a bullet.
- Self-update: a run asks once an hour whether the installed code is still the
  newest, and updates itself between two runs.
- `ticket-runner history` shows what each ticket cost and how long it took.
- A dated ticket waits for its date.
- An architecture diagram, generated by [archify](https://github.com/tt-a1i/archify)
  from `diagrams/ticket-runner.architecture.json`: a still in the README and an
  interactive `diagrams/architecture.html` whose nodes link to the code they are
  drawn from.
- A *Validated* column: the answer to the question *In review* asks. Move a
  ticket there and the runner does the last thing it needs — it merges its pull
  request (`runner.merge_method`, `squash` by default), or, when there is none,
  runs a session that publishes what the ticket already holds: the post, the
  mail, the announcement. Then *Done*, which now means out in the world rather
  than merely finished. A run that dies mid-publication comes back as a question
  rather than redoing the work, publications of one pass run side by side, and
  `--dry-run` says what it would merge or publish without touching anything.
  Optional: a board without the column behaves exactly as before, and
  `ticket-runner init` adds it.
- A **Settings** tab in the web console: `config.toml` drawn as a page, every
  key of it, written back into that very file one line at a time — the comments
  around it survive, and the console picks the change up without a restart. A
  blank field says nothing and shows the default it falls back on; tokens are
  never sent to the browser, only *set, ending in …f3a2*; and a save is all of
  it or none of it, on a copy that has to load before it takes the file's place.
- A release and versioning system: this changelog, `scripts/release.py`, the
  `release` workflow, and the `/release` command Claude uses to cut one.
- `ticket-runner`, typed alone, presents itself: the product, the version it is
  running, an update waiting if there is one, and the commands — rather than an
  argparse usage block. The web console prints the same version beside its name
  in the header, so a browser tab left open says which runner it is talking to.

### Changed

- **The web console starts on its own.** Its unit was installed and left
  stopped, so the board only existed for as long as you remembered to type
  `ticket-runner serve` in a terminal you then had to leave open. It is now
  armed with the timer — by `install.sh` on a new machine, by `ticket-runner
  enable` on one that already has the runner — so `http://127.0.0.1:8787` is up
  after a boot with nothing to type, and the installer prints the address with
  the token in it rather than leaving it in a state file. What it opens is
  loopback and nothing else, which is what makes it a reasonable default;
  widening `web.host` is still the decision it always was. `TR_NO_WEB=1 sh
  install.sh` installs the unit and leaves it stopped, `ticket-runner disable`
  stops both — from a terminal, the console's own command line refusing the one
  command that would cut it off mid-answer — and `ticket-runner serve` on a
  machine where the console is already listening says where it is instead of
  failing on the port.
- The console's scroll bars are the console's own: thin, rounded, the colour of
  its panels, and only really visible under the pointer. The browser's — pale,
  wide, and drawn for a white page — turned up in every part of the console
  that scrolls, which is nearly all of it: the board, the transcript, a
  session's steps, the settings. The dropdowns and the caret follow the same
  dark now.

### Fixed

- `ticket-runner clean --force` removes the branch of every worktree it
  removes. A branch is named after its ticket, so a failed session left one
  behind that made every later attempt answer `branch ticket/… already exists`:
  the ticket was stuck for good, and `clean` — which only ever removed the
  directory — did not help. It does now, and it stops where something would be
  lost: a branch with commits of its own, one whose pull request is still open,
  or a worktree with uncommitted changes is kept, named in the output with the
  reason and with the command that drops it once you have looked.
