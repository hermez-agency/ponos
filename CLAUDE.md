# CLAUDE.md

Ce fichier oriente Claude Code (ou tout agent) dans ce dépôt. Le README fait
référence : il est très détaillé, ne le duplique pas ici et ne le résume pas —
sers-t'en pour toute question de comportement ou de configuration.

## Le projet, en deux phrases

`ponos` exécute des tickets Notion avec Claude Code : un ticket passé
en *Ready* devient une session Claude, sur un `git worktree` jetable propre à
ce ticket, et revient en pull request ou en page Notion publiée. Le cœur tourne
en continu sur la machine de l'utilisateur ; un console web optionnelle et des
canaux (Telegram, Slack) permettent de suivre le travail ou d'y répondre.

## Stack et versions qui comptent

Deux mondes séparés, à ne pas mélanger :

- **Cœur** — Python 3.11+, la bibliothèque standard et quatre dépendances
  d'exécution : **httpx** et **pydantic** pour le runner, **FastAPI** servi par
  **uvicorn** pour la console (`web/app.py`, `web/routes.py`) — `dependencies` dans
  `pyproject.toml`, exportées avec leurs sommes dans `requirements.txt`. Le
  groupe `dev` porte l'outillage (ruff, mypy, pytest, pytest-cov), le tout figé
  dans `uv.lock`. Chaque version installée a son `.venv` (`environment.py`), qui
  reçoit `requirements.txt` avant la bascule ; l'image l'installe au build. Les
  suites de tests tournent dans le `.venv` de `uv sync`, ou avec un `python3` où
  `requirements.txt` est installé ; `python3 tests/run.py` se relance dans le
  `.venv` du dépôt quand `python3` n'a pas FastAPI.
- **`frontend/`** — sous-projet séparé : React 19, TypeScript, Vite 8,
  shadcn/ui sur Tailwind 4. Géré par npm (`package-lock.json`). Node n'est
  nécessaire que pour *modifier* la console, jamais pour l'installer ou
  l'exécuter.

## Commandes réelles

Cœur Python — pas de build :

```sh
uv sync                      # httpx et l'outillage, aux versions de uv.lock, dans .venv
uv run python tests/run.py         # la partie pure : ne touche ni Notion, ni git, ni le réseau (-j 1 : en série)
uv run python tests/functional.py  # le parcours complet, sur des doublures locales
uv run pytest                # les deux suites sous pytest, un worker par cœur (-n 0 : en série ; -m "not functional" : la partie pure)
uv run pytest tests/test_update.py  # les cas d'un seul module
uv run ruff check .          # le lint de la CI
uv run ruff format .         # le format, que la CI vérifie aussi (--check)
uv run mypy                  # les types, comme la CI : strict partout sauf la liste d'exceptions
uv run pre-commit install    # une fois par clone : ruff, format, uv.lock, requirements.txt et web/static avant chaque commit
uv run --frozen pre-commit run --all-files  # les mêmes hooks sur tout l'arbre (--frozen : sinon uv met uv.lock à jour avant le hook)
```

Un nouveau cas s'écrit toujours avec `@case`, dans le `tests/test_<module>.py`
du module qu'il teste (ou dans `tests/functional.py`) : `tests/run.py` importe
tous les `tests/test_*.py`, et `tests/conftest.py` donne les mêmes cas à pytest.
Ce qu'un cas met en place autour de lui se demande par un paramètre — une
fixture écrite avec `@fixture` dans `tests/support.py` (`state_home`,
`installation`) ou `tests/functional.py` (`machine`) — que les deux lanceurs
ouvrent. Les deux scripts répartissent les cas sur un processus par cœur, comme
`pytest -n auto` : aucun cas ne doit dépendre d'un autre lancé avant lui.

Frontend, depuis `frontend/` :

```sh
npm install
npm run build   # tsc -b && vite build — écrit dans ../src/ponos/web/static
npm run lint    # tsc -b --noEmit
npm run types   # src/lib/api-types.d.ts, depuis le schéma OpenAPI de la console (scripts/openapi.py)
npm run test:e2e  # Playwright dans le Chrome installé, sur un vrai `serve` et un board jetable
npm run test:e2e:ci  # le même, avec les deux workers de la CI : c’est lui qui montre une dépendance à l’ordre
npm test        # node --test src/lib/*.test.ts — la logique de la barre de message, sans navigateur
npm run test:components  # Vitest + Testing Library dans jsdom : src/**/*.test.tsx, un composant à la fois
npm run dev     # serveur de dev avec hot reload, proxy /api vers un console déjà lancé
npm run dev:demo  # le même, sur la console de démo (ci-dessous) : fausses données, ni Notion ni réseau
```

Travailler la console sans rien de réel, en trois lignes : `python3 scripts/demo.py`
(un vrai `ponos serve` sur un board jetable, port 8791, jeton `demo`, état temporaire effacé à
l'arrêt) ; `cd frontend && npm run dev:demo` ; ouvrir une fois
`http://127.0.0.1:8791/?token=demo` (le cookie), puis `http://127.0.0.1:5173`. Ses données
(`scripts/demo.py`) ne sont pas celles des e2e (`frontend/e2e/console.py`) : les deux ne
partagent que `scripts/workbench.py`, le harnais (faux `claude`, `gh`, `systemctl`, état à part).

## CI

`.github/workflows/ci.yml` tourne sur chaque pull request et sur chaque push
vers `main` : le job cœur installe `requirements.txt` (et rien d'autre), puis
relance `python3 tests/run.py` et `python3 tests/functional.py` sous Python 3.11
et 3.13 ; le job qualité fait `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy`, vérifie que
`requirements.txt` est l'export de `uv.lock`, puis `pytest --cov --cov-fail-under=80`
(réparti par pytest-xdist, sous-processus Python compris dans la couverture) ; le job frontend ne se déclenche que si `frontend/**` ou
`src/ponos/web/**` a changé, et y
fait `npm ci`, échoue si `npm run types` change `src/lib/api-types.d.ts`, puis
`npm run lint`, `npm test`, `npm run build` (sous Node 24),
échoue si `src/ponos/web/static` diffère de ce que le build vient
d'écrire, puis lance `npm run test:e2e` sur ce `requirements.txt` installé.
Un job `image` construit le `Dockerfile` et relance `tests/functional.py`
dedans. `release.yml` reste séparé, ne se déclenche que sur un tag, relance les
deux suites, puis publie l'image sur `ghcr.io`.

## Arborescence utile

- `src/ponos/` — le cœur. Un run reste **un seul objet**, découpé par
  responsabilité : `base.py` porte son état (le board, caches, voix) et
  son docstring explique la forme choisie ; `runner.py` ne garde que la passe
  (`tick`, `_work`) ; chaque chapitre a son module — `board.py` (lire le
  tableau, le remettre d'aplomb), `preparation.py` (localiser le projet,
  réclamer le ticket), `execution.py` (la session, et ce qu'un ticket en
  rapporte), `delivery.py` (la colonne validée : fusionner, publier),
  `recurrence.py` (les tickets qui reviennent seuls), `replies.py` (répondre
  aux commentaires), `transitions.py` (la colonne `On` : le prompt d'un ticket
  à chaque changement de statut), `reports.py` (ce qui s'écrit sur un ticket et ce qui
  atteint ton téléphone), `ticket.py` (`Ticket` et `Job`, sans dépendance).
- `src/ponos/` — autour du run : `config.py` (et `schema.py`, ce que chaque table de
  `config.toml` peut dire, en modèles pydantic ; `project_settings.py`, ce qu'un
  projet décide pour lui-même par-dessus, gardé dans `ponos.db`), `store.py` (la couture
  vers un tableau, quel qu'il soit) et les trois qui la remplissent —
  `notion.py`, `files.py` (le board en fichiers Markdown), `sync.py` (les deux
  en phase) —, `health.py` (les vérifications que le dashboard et `ponos doctor` partagent, et les corrections qu'il propose), `git.py`, `github_app.py` (la GitHub App créée depuis la console,
  ses jetons d'installation, devant `gh`), `session.py`, `provider.py` (qui répond aux sessions :
  le CLI connecté, une clé Anthropic ou OpenRouter), `voice.py` (les mots et la langue),
  `vault.py` (les clés que `[vault]` donne aux sessions d'un projet, et leur masquage partout où le runner écrit),
  `passwords.py` (le mot de passe de la console, gardé en digest scrypt),
  `http.py` (le seul client HTTP : un `httpx.Client` par service et la
  politique de réessai de Notion pour tous — les tests y branchent un
  `httpx.MockTransport`),
  `log.py` (le journal `ponos.log` : un logger par module, la trace de chaque
  erreur rattrapée, le masquage des secrets avant l'écriture),
  `channels/` (Telegram, Slack), `web/` (la console : `server.py` la porte —
  jeton, connexion, pages d'avant, `serve` —, `app.py` l'application FastAPI —
  la garde en middleware, le flux SSE, MCP et OAuth —, `routes.py` l'API,
  `answers.py` les formes de ce qu'elle répond, d'où viennent les types de la page ;
  `web/attempts.py` compte les tentatives ratées par adresse, `web/sessions.py` date et
  révoque les connexions ;
  `web/console.py` tient la conversation avec l'espace de travail,
  `web/agui.py` la traduit en AG-UI pour le `useChat` de la page, et
  `web/attachments.py` les fichiers qu'un message y emporte).
- `src/ponos/web/static/` — **généré**, pas du code source à modifier
  à la main (voir Pièges connus).
- `frontend/` — sous-projet React/TypeScript/Vite de la console web. La
  conversation est `useChat` de TanStack AI (`src/lib/agui.ts` : la connexion,
  abonnée aux événements AG-UI de `/api/events`), dessinée par le kit de chat
  de Brand Assets, repris et adapté dans `src/components/chat/`. La barre
  de message est un composant réutilisable,
  `frontend/src/components/console/composer.tsx` ; ses décisions sans DOM
  (fichiers acceptés, collage, bouton d'envoi, autocomplétion `>`) vivent dans
  `frontend/src/lib/composer.ts`, qui n'importe rien pour que `node --test` le
  lise tel quel.
- `bin/ponos.in` — gabarit du script installé par `install.sh`
  (`@APP_DIR@` et `@PYTHON@` y sont substitués).
- `tests/test_<module>.py` — la suite du cœur, un fichier par module, sans
  framework ; `tests/support.py` porte ce que plusieurs fichiers partagent
  (doublures, fixtures, `@case`) et `tests/run.py` les lance tous.
- `tests/functional.py` — les tests du parcours complet, avec leurs doublures :
  un faux Notion en local (`http.server`), un dépôt git et son remote bare, un
  `claude` et un `gh` en tête du `PATH`. Le seul point d'injection côté cœur est
  `PONOS_NOTION_API` (voir `notion.endpoint`).
- `Dockerfile`, `docker-compose.yml`, `docker/entrypoint.sh` — l'image : une
  autre façon d'installer, pas un autre programme. `PONOS_CONTAINER` y dit au
  cœur qu'il n'y a ni systemd ni mise à jour automatique (`config.in_container`).
- `systemd/` — gabarits des unités (`.service.in`, `.timer.in`) posées par
  `install.sh` pour le timer et la console.
- `desktop/` — gabarit du handler `ponos://` enregistré sur le bureau.
- `diagrams/` — `ponos.architecture.json` est la source du diagramme ;
  `architecture.html` et `ponos.png` en sont générés, voir le README
  ("Regenerating it").

## Conventions de code et de commit

- `from __future__ import annotations` en tête de chaque module du cœur, et
  des annotations de type partout.
- Le cœur n'importe que la bibliothèque standard, ses propres modules,
  httpx et pydantic — httpx seulement dans `http.py` : une requête passe par
  `http.send`, jamais par `urllib.request` ; pydantic seulement dans
  `schema.py`, que `config.load` importe en lisant le fichier, pour qu'une
  passe sur le `python3` de la machine fabrique encore le `.venv`. FastAPI (et ce qu'il tire) n'entre
  que dans `web/app.py`, `web/routes.py` et `web/answers.py` — un test le vérifie. Un autre
  paquet tiers n'entre que par le ticket qui le décide (voir l'audit), déclaré
  dans `pyproject.toml` et exporté dans `requirements.txt` — jamais au détour
  d'un autre changement.
- Les docstrings de module expliquent le *pourquoi* d'un choix (souvent non
  évident), pas ce que fait le fichier — voir `naming.py` ou `tests/run.py`
  pour le ton attendu. Continue dans ce style plutôt que d'ajouter des
  docstrings passe-partout.
- Messages de commit : une phrase descriptive au fil, sans préfixe imposé
  (`feat:`/`fix:`/`docs:` apparaissent parfois mais ne sont pas systématiques).
  Le dépôt mélange anglais et français selon qui a écrit le commit — reste
  cohérent avec le ticket que tu traites plutôt que de forcer une langue.
- Le frontend suit la configuration TypeScript stricte du dépôt
  (`tsc -b --noEmit` est le seul lint) et les sentences affichées passent par
  `t("...")` de `react-mini-i18n` — la phrase anglaise est la clé, la
  traduction française vit dans `frontend/src/lib/french.ts` — sauf celles des
  vérifications de `health.py`, dans `frontend/src/lib/health-french.ts`, que la
  bande de santé charge quand elle s'affiche (budget du premier chargement).

## Pièges connus

- **`src/ponos/web/static/` est un artefact commité, pas du code à
  éditer à la main.** Il est réécrit intégralement par `npm run build` depuis
  `frontend/` — le runner s'installe avec `python3` et `git` seulement, donc ce
  répertoire doit rester dans le dépôt et à jour à chaque changement de la
  console.
- **Les types de l'API ne s'écrivent pas dans le frontend.** Une clé que
  l'API ajoute, renomme ou retire se dit dans `web/answers.py` (et la route
  la nomme par `response_model=`), puis `npm run types` réécrit
  `frontend/src/lib/api-types.d.ts`, généré et commité ; `types.ts` n'en
  garde que les noms. La CI régénère le fichier et refuse un écart.
- **`web/server.py` reste en bibliothèque standard.** Une installation encore
  en v0.1.0 vérifie une nouvelle version en important `ponos.web.server` avec le
  `python3` de la machine (`update.verify`) : y importer FastAPI bloquerait
  pour de bon la mise à jour qui l'apporte. Ce qui en a besoin va dans
  `web/app.py`, que `serve` importe au moment de servir.
- **`docs/` est le site public, pas une documentation interne.** `docs/CNAME` en
  fait la racine GitHub Pages de the-ponos.app : tout fichier posé là est servi,
  lié ou non. Audits, notes et plans vont dans `notes/` (ou dans Notion) ; un
  test de `tests/test_release.py` refuse un `.md` sous `docs/` et toute entrée
  de sa racine qui n'est pas dans la liste du site.
- **`diagrams/architecture.html` ne s'édite jamais directement.** Il est
  généré par l'outil `archify` à partir de
  `diagrams/ponos.architecture.json`, qui est le fichier à modifier.
- **Ne jamais toucher au dépôt principal de l'utilisateur.** Chaque ticket
  travaille sur un `git worktree` jetable et sa propre branche ; le code du
  runner qui manipule des worktrees (`git.py`, `execution.py`) doit préserver
  cette isolation.
- **Une méthode nouvelle va dans son chapitre, pas dans `runner.py`.** Les
  classes de `board.py`, `execution.py` et consorts s'assemblent sur `Base` et
  partagent le `self` d'un run : ajouter une méthode, c'est l'écrire dans le
  module dont elle relève. `runner.py` n'a que la passe, et tient sous
  300 lignes pour cette raison.
- **Les types de fichiers acceptés sont écrits deux fois.** `ACCEPTED` dans
  `web/attachments.py` (ce que le serveur garde et sert) et dans
  `frontend/src/lib/composer.ts` (ce que la page refuse d'emblée) : un test
  vérifie qu'ils concordent. N'y ajouter ni HTML ni SVG — les fichiers sont
  resservis depuis l'origine de la console.
- **Les formes de token sont écrites deux fois.** `TOKENS` dans `redaction.py`
  (ce que le runner masque avant d'écrire un commentaire) et dans
  `frontend/src/lib/secrets.ts` (ce dont la console avertit avant l'envoi) :
  un test vérifie qu'elles concordent.
- **Deux phrases identiques, deux endroits.** Certaines chaînes affichées par
  la console (nom d'un réglage, texte d'aide) viennent de `web/settings.py`
  côté Python et sont recherchées par leur texte exact côté React — renommer
  l'une sans l'autre casse un test.
- **`config.example.toml` documente chaque clé en commentaire.** Une nouvelle
  clé de configuration sans son commentaire, ou sans mise à jour de
  `ponos doctor`, part du mauvais pied.
- **Une dépendance d'exécution ne s'ajoute pas en passant.** Le socle est là
  (`pyproject.toml`, `uv.lock`, un `.venv` par version installée), mais chaque
  bibliothèque a son ticket, dans l'ordre de `notes/audit-technique-2026-10.md`.
  Elle s'ajoute avec `uv add`, puis `uv export --no-dev --no-emit-project
  --format requirements-txt -o requirements.txt` (la CI vérifie l'export), et
  l'image l'installe au build.
- **Le ticket « Réparer main » est un ticket Code / Bug, validé sans attendre.**
  `delivery._repair` le crée en type Code, sous-type Bug, priorité 75 ; sa PR, dont la CI doit être
  entièrement verte (`_force_merge`), est fusionnée par le runner même sans *Force validated*
  (`_forced`, via `state.is_repair`), puis les PR mises de côté sont rejouées par `_waits_for_base`.
  Ne pas la laisser en *In review* : toutes les autres PR du dépôt attendent derrière elle.
- **La version est écrite deux fois** : `__version__` et `pyproject.toml`.
  `scripts/release.py bump` écrit les deux, `check` et un test refusent un écart.
- **Ruff n'a pas de base d'exceptions.** `[tool.ruff.lint.per-file-ignores]`
  a été vidé ; un écart se corrige, ou se justifie par un `# noqa` sur sa
  ligne. Le commit qui a passé `ruff format` sur tout le dépôt est dans
  `.git-blame-ignore-revs` (`git config blame.ignoreRevsFile
  .git-blame-ignore-revs` pour que `git blame` l'enjambe en local).
- **mypy est strict partout, sauf une liste d'exceptions qui ne fait que
  rétrécir.** `[tool.mypy]` met `strict` pour tout le cœur ; le premier
  `[[tool.mypy.overrides]]` garde en mode souple les modules pas encore
  stricts, le second ignore ceux qui ne passent même pas en souple. Un
  nouveau module n'entre dans aucune des deux ; un module sorti d'une liste
  n'y revient pas — un écart se corrige, ou se justifie par un
  `# type: ignore[code]` sur sa ligne.
