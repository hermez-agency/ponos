# Audit technique de Ponos — octobre 2026

Mesuré le 19 octobre 2026 sur `main` (`5ec72aa`), sur cette machine et dans la CI.
Chaque recommandation a un ticket brouillon dans Notion (projet Ponos, type Code) ;
l'ordre et les dépendances ci-dessous sont ceux des briefs.

## En bref

Ponos tient : 43 000 lignes de Python, 86 fichiers, 789 cas de test qui passent, 80 %
de lignes couvertes, une mise à jour atomique avec retour arrière. Ce qui coûte
aujourd'hui, ce n'est pas un bug précis, c'est **la vitesse à laquelle on peut changer
le code sans casse** : six fonctions de plus de 200 lignes, un fichier de tests de
20 741 lignes, aucun journal (`logging` n'est importé nulle part), neuf clients HTTP
écrits à la main dont un seul sait réessayer, et 1 002 lignes de types TypeScript
recopiées à la main depuis des `dict` Python.

**Les cinq changements, dans l'ordre :**

1. **Le socle de cette PR** — `pyproject.toml`, `uv.lock`, ruff, pytest, job CI, et un
   `.venv` par version installée. Rien ne change pour l'utilisateur ; tout le reste en
   dépend.
2. **Durcir la console** (sécurité) — mot de passe en clair, aucune limite de tentatives,
   pas de CSP sur la page. Indépendant du reste : à faire tout de suite.
3. **Un vrai journal** (`logging`) et plus aucune erreur avalée — c'est ce qui manque le
   plus quand un blocage arrive sur une machine sans personne devant.
4. **La première dépendance : un client HTTP unique sur httpx** — précédé d'un `doctor`
   qui vérifie l'environnement. C'est le test grandeur nature du `.venv`.
5. **La chaîne de la console** : découper les fonctions géantes → config en pydantic →
   console sur FastAPI → `types.ts` généré depuis OpenAPI.

Non recommandé : Typer/Click, alembic/sqlite-utils, structlog, le SDK `notion-client`
(raisons en § 3).

## 1. Contraintes, noir sur blanc

Toute recommandation de ce document, et tout ticket qui en sort, respecte ceci :

- **Installation et mise à jour automatique.** `install.sh` clone dans
  `~/.local/share/ponos/app-<commit>` et `app` est un lien basculé en un `rename`.
  Depuis cette PR, chaque version a **son propre `.venv`**, créé *avant* la bascule
  (`environment.py`) : une version dont l'environnement ne se crée pas n'est jamais
  pointée, celle en service garde le sien — c'est le retour arrière. Une dépendance
  d'exécution s'ajoute avec `uv add`, et `requirements.txt` (export de `uv.lock`, avec
  hachages, vérifié en CI) est ce que les installations installent.
- **Aucune régression pour une installation en place.** La première mise à jour vers ce
  code est faite par l'ancien code, qui ne connaît pas `.venv` : le lanceur retombe sur
  le `python3` de la machine, et la passe suivante crée l'environnement. Vérifié de bout
  en bout (§ 6).
- **Python minimal : 3.11** (`tomllib`). `requires-python = ">=3.11"`, CI sur 3.11 et
  3.13. Toute dépendance retenue doit supporter 3.11.
- **Debian/Ubuntu sans `python3-venv`** (cette machine en est une) : `venv` y marche
  avec `--without-pip`, pas avec pip. Tant que `requirements.txt` est vide, rien à
  faire ; **avant la première dépendance**, il faut que l'installation sache installer
  sans pip (uv amorcé) — c'est le ticket « Environnement » (§ 5, n° 5).
- **Image Docker et template Dokploy.** L'image installe `requirements.txt` dans son
  Python au build (étape ajoutée, vide aujourd'hui) ; pas de `.venv` dans un conteneur.
  Le template Dokploy épingle une image : rien à changer.
- **Bureau (`desktop/`).** Le handler `ponos://` appelle le lanceur : il hérite du
  `.venv` sans changement.
- **`python3 tests/run.py` reste lançable sans rien installer** — le job CI « cœur » le
  prouve à chaque PR.

## 2. Constats, par gravité

### Haute

- **La console exécute du code sur la machine** (sessions en `bypassPermissions` depuis
  le chat et les tickets) et sa porte est plus faible qu'elle ne devrait :
  - mot de passe gardé **en clair** dans `secrets.env` et comparé en clair
    (`web/server.py:1295`), au lieu d'un hachage (`hashlib.scrypt` est dans la stdlib) ;
  - **aucune limite de tentatives** : un `sleep(1)` dans le thread de la requête, que
    `ThreadingHTTPServer` contourne en parallélisant ;
  - cookie de session sans expiration côté serveur ;
  - pas de **CSP** sur `index.html` ni l'API, ni `Permissions-Policy`, COOP, CORP, HSTS
    (présents : `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`) ;
  - `allowed_users` vide par défaut pour Telegram et Slack : tout membre du canal répond.
  Le reste est sain : token de 192 bits, `hmac.compare_digest` partout, `SameSite=Strict`,
  `HttpOnly`, garde `X-Ponos` sur chaque POST, écoute sur loopback par défaut, refus
  d'une adresse publique sans identifiants, secrets en 0600 hors de `config.toml`.
- **Des erreurs disparaissent.** Aucun `import logging` dans `src/ponos` ; 191 `print`,
  397 `say`. `log_message` du serveur est désactivé, si bien que les trois `except
  Exception` de `web/server.py` (659, 882, 1014) renvoient un 500 **sans laisser de
  trace** ; cinq `except Exception` se terminent par `pass`/`return`/`continue`
  (`web/server.py` ×3, `web/setup.py`, `web/upgrade.py:207`).

### Moyenne

- **Fonctions géantes** : 17 fonctions de plus de 100 lignes, 6 de plus de 200 —
  `command_doctor` 517, `config.load` 390, `_execute_code` 286, `do_GET` 230, `do_POST`
  222, `session.run` 214. Ce sont aussi les zones les moins couvertes : `__main__.py`
  26 %, `web/server.py` 63 %.
- **HTTP à la main, sept fois** : 9 `urlopen` dans 7 modules. Seul Notion réessaie
  (4 essais, `Retry-After` respecté, rejeu limité aux requêtes idempotentes — bien fait) ;
  GitHub, OpenRouter, Telegram/Slack, images et MCP n'ont **ni réessai ni gestion du
  429**. La pagination Notion est recopiée 5 fois.
- **Couplage console → cœur** : `web/api.py` importe ~35 modules du cœur et instancie un
  `Runner` (12 mixins), utilisé 74 fois ; `web/api.py` importe `__main__` (le web dépend
  du CLI) ; 36 imports placés dans des fonctions pour esquiver des cycles.
- **Contrat front/back implicite** : `frontend/src/lib/types.ts` (1 002 lignes, 86
  types) recopie à la main des `dict` Python sans aucun schéma — une clé renommée côté
  Python ne casse rien avant le navigateur.
- **Configuration validée à la main** : `config.load` fait 390 lignes de `raw.get()`,
  11 dataclasses, 5 `raise` dans tout le fichier : une valeur fausse est le plus souvent
  remplacée en silence par la valeur par défaut.
- **`gh repo clone <repository>` sans `--`** (`git.py:227`) : le nom vient d'une page
  Notion non validée ; une valeur commençant par `-` serait lue comme une option.

### Basse

- Fichiers statiques servis après un test de préfixe sans séparateur
  (`startswith(str(STATIC))`) au lieu de `is_relative_to` — non exploitable aujourd'hui.
- `?token=` accepté sur toutes les routes GET (fuite possible dans l'historique).
- `ruff` relève peu de choses : 14 erreurs pyflakes (imports morts, variables inutilisées
  — 4 corrigées ici, le reste en base d'exceptions), 25 bugbear, 116 `UP`, 16 `I` ;
  `ruff format` reformaterait 73 fichiers sur 89.

### Ce qui va bien (à ne pas casser)

- Migrations SQLite (`db.py`) : 26 migrations nommées, `PRAGMA user_version` + table
  `migrations`, chacune dans son `BEGIN IMMEDIATE` avec `ROLLBACK`, refus d'une base plus
  récente que le code (`TooNew`), WAL. **Rien à gagner avec alembic.**
- Mise à jour atomique (`update.py`) : répertoire par version, vérification d'import
  avant bascule, retour arrière, verrou de run.
- Aucun `shell=True`, `os.system` ni `os.popen` (40 appels `subprocess`, liste
  d'arguments) ; les noms de branche passent par `slugify` (`[a-z0-9-]`, tirets de tête
  retirés).
- Pièces jointes et journaux : identifiants contrôlés, noms nettoyés.

### L'historique des blocages

314 commits en sept semaines. Les sujets parlent de `session` (31), `bloqué/blocked`
(35), `migration` (10), `worktree` (8), `conflit` (8), `mise à jour` (7), `rejeu` (3).
Les épisodes les plus coûteux ont tous été réglés par une garde ajoutée **après** coup :
une passe lancée pendant une mise à jour (`ImportError: SLOTS`, 30/09 → répertoire par
version), une base migrée par le code d'une branche (#213 → migrations nommées), une
console restée sur l'ancien code (#70 → redémarrage), des worktrees interrompus ou
laissés par Docker. Le point commun : **le symptôme était visible, la cause non** — d'où
la priorité donnée au journal (n° 3).

## 3. Les dépendances évaluées

| Candidat | Remplace | Gain | Coût | Verdict |
|---|---|---|---|---|
| **pyproject + uv** | rien (pas de métadonnées) | lockfile, venv reproductible, `uv run` | aucun à l'exécution | **fait ici** |
| **ruff** (lint) | rien | 15 défauts réels trouvés, CI | outil dev | **fait ici** ; format → ticket |
| **pytest + pytest-cov** | `tests/run.py` comme lanceur | `-k`, `-x`, durées, couverture | outil dev | **fait ici** (pont sans réécriture) |
| **mypy** | les annotations non vérifiées | annotations déjà partout : gain immédiat | outil dev, bruit au début | ticket, mode progressif |
| pyright | idem | plus rapide | dépend de Node | non : mypy suffit, pas de Node côté Python |
| **pre-commit** | rien | ruff avant le push | outil dev | ticket (petit) |
| **httpx** | 9 `urlopen` | délais, pool, HTTP/2, `MockTransport` pour les tests | ~5 paquets purs Python, mûr | **1ʳᵉ dépendance d'exécution** |
| tenacity | la boucle de réessai Notion | déclaratif | un paquet de plus | non pour l'instant : la politique Notion (40 lignes, testée) est reprise telle quelle dans le client commun |
| notion-client (SDK) | `notion.py` | — | une couche de plus, suit l'API avec retard, Ponos n'utilise qu'une poignée d'endpoints | non |
| **pydantic v2** | `config.load`, payloads de l'API | validation, erreurs lisibles, schéma JSON | ~2 Mo (cœur Rust compilé : roues disponibles pour Linux x86-64/arm64) | ticket, après httpx |
| pydantic-settings | lecture de `secrets.env` / env | — | — | optionnel, à décider dans le ticket config |
| **FastAPI + uvicorn** | `http.server`, routage regex, SSE à la main | validation, OpenAPI → types TS, tests `TestClient` | dépendances (Starlette, pydantic, anyio, uvicorn) ; réécriture du serveur | ticket, après pydantic |
| Starlette seul | idem | plus léger | pas d'OpenAPI | non : l'OpenAPI est le gain principal |
| Typer / Click | `argparse` | moins de code | `argparse` marche, la console lit la liste des sous-commandes dans le parser | non : découper `command_doctor` suffit |
| alembic / sqlite-utils | `db.py` | — | ORM/outillage inutiles, migrations actuelles solides | non |
| `logging` (stdlib) | `print`/`say` | niveaux, fichier, traces | aucun | ticket |
| structlog | — | JSON structuré | une dépendance | non : `logging` d'abord, structlog si un jour on agrège |

## 4. Qualité, tests et CI

- **Suites** : `tests/run.py` 745 cas (≈46 s ici), `tests/functional.py` 44 cas (≈92 s ;
  ≈4 min 40 dans l'image Docker de la CI). Sous pytest : 789 tests, 2 min 17.
- **Couverture** : **80 %** des lignes (17 698 instructions, 3 626 non couvertes). Les
  trous : `__main__.py` 26 %, `web/setup.py` 43 %, `unblocking.py` 53 %, `provider.py`
  63 %, `web/server.py` 63 %, `legacy.py` 64 %.
- **Tests lents** : les dix plus lents sont fonctionnels, 3 à 6 s chacun (fusions en
  série, conflits). Rien d'instable observé dans les deux suites Python sur cette
  machine.
- **Un fichier de 20 741 lignes** : `tests/run.py`. Il se lit mal, se fusionne mal
  (conflits fréquents entre tickets parallèles) et force un ordre unique.
- **CI** (100 derniers runs) : 85 verts, 13 rouges, 2 annulés. Les rouges : cœur ×8,
  frontend ×5 (`npm run test:e2e:ci`, dont un sur `main`). Durée par job : cœur ≈2 min,
  image ≈4–6 min, frontend ≈6 min quand il tourne (filtré sur `frontend/**` et
  `src/ponos/web/**`) ; ≈6 min de bout en bout. Le nouveau job qualité ajoute ≈2 min 30
  en parallèle, sans allonger le total.
- **Front** : 40 fichiers e2e Playwright (≈205 tests), 24 fichiers `node --test`.

## 5. Les recommandations (= les tickets brouillons)

Chaque ligne : sous-type · pourquoi · coût · « à faire après ».

1. **Ruff : vider la base d'exceptions, puis `ruff format`** · Chore · reprend le
   brouillon « Linter ruff… ». Activer `I` et `UP` (`--fix`), corriger les 25 bugbear,
   puis reformater en **un commit isolé** listé dans `.git-blame-ignore-revs`, et
   ajouter `ruff format --check` à la CI. · ½ jour · après ce socle.
2. **pre-commit** · Chore · ruff, `ruff format`, `uv lock --check`, garde des fichiers
   générés (`web/static`). · 1 h · après 1.
3. **mypy en CI, progressif** · Chore · commencer par les modules purs (`ticket`,
   `naming`, `markdown`, `db`), `strict` module par module. · 1–2 j · après 1.
4. **Journal et erreurs avalées** · Refactor · `logging` stdlib vers
   `~/.local/state/ponos/logs/ponos.log` (rotation) + journald ; `log_message` du serveur
   branché dessus ; chaque `except Exception` journalise la trace. · 1–2 j · après ce
   socle.
5. **Environnement : `doctor` et installation sans pip** · Chore · `ponos doctor` vérifie
   le `.venv` de la version en service ; si `requirements.txt` n'est pas vide et que le
   Python n'a pas `ensurepip`, l'installation amorce uv (binaire statique, vérifié par
   somme) ; test sur Debian sans `python3-venv`. · 1 j · après ce socle ; **avant toute
   dépendance d'exécution**.
6. **Un client HTTP unique sur httpx** · Refactor · `ponos/http.py` : délais, User-Agent,
   politique de réessai de Notion (idempotence, `Retry-After`) pour tous ; GitHub,
   OpenRouter, canaux, images, MCP y passent ; pagination Notion factorisée ; tests sur
   `httpx.MockTransport`. · 2–3 j · après 4 et 5.
7. **Découper les fonctions géantes** · Refactor · reprend le brouillon « Découper les
   fonctions géantes… » : `command_doctor` (517), `config.load` (390), `_execute_code`
   (286), `do_GET`/`do_POST`, `session.run` ; sortie de `doctor` identique avant/après. ·
   3–4 j · après 1.
8. **Configuration validée par pydantic** · Refactor · modèles pydantic v2 pour
   `config.toml` (mêmes valeurs par défaut, erreurs nommant la clé), `doctor` qui les
   affiche ; `config.example.toml` testé contre le modèle. · 2–3 j · après 6 et 7.
9. **Console sur FastAPI + uvicorn** · Refactor · reprend le brouillon « FastAPI pour la
   console… », mais dans le `.venv` de la version (pas un venv à part) ; mêmes routes,
   même garde, SSE par `StreamingResponse`, e2e Playwright comme filet. · 1–2 sem. ·
   après 4, 8 et 10 (sécurité).
10. **Durcir la console** · Sécurité · mot de passe haché (`hashlib.scrypt`), limite de
    tentatives par IP, expiration des sessions, CSP sur la page, `Permissions-Policy`,
    COOP/CORP, `--` avant les noms de dépôt passés à `gh`, `is_relative_to` pour les
    statiques, `allowed_users` signalé par `doctor` quand il est vide. · 2 j · **sans
    prérequis : en premier.**
11. **`types.ts` généré depuis OpenAPI** · Chore · reprend le brouillon « Frontend :
    types.ts généré… » : `openapi-typescript` sur le schéma FastAPI, contrôle de dérive en
    CI. · 1–2 j · après 9.
12. **Tests : découper `tests/run.py`, paralléliser, seuil de couverture** · Chore · un
    fichier par module, fixtures pytest à la place de `_state_home`/`bench`,
    `pytest-xdist`, `--cov-fail-under=80` ; `python3 tests/run.py` garde un point
    d'entrée. · 2–3 j · après 1.
13. **Front : dépendances et poids** · Perf · voir § 7. · 1 j · sans prérequis.

## 6. Ce que cette PR livre

- `pyproject.toml` (métadonnées, `requires-python >= 3.11`, `dependencies = []`, groupe
  `dev` : pytest, pytest-cov, ruff), `uv.lock`, `requirements.txt` (export vide).
- **ruff** : `E4 E7 E9 F W B`, ligne à 100 ; 4 défauts corrigés dans `src/`, le reste en
  base d'exceptions par fichier. `ruff format` non imposé (73 fichiers).
- **pytest** : `tests/test_suites.py` donne à pytest les 789 cas existants tels quels ;
  marqueur `functional`.
- **CI** : job `quality` — `uv sync --locked`, `ruff check`, contrôle de l'export
  `requirements.txt`, `pytest --cov`.
- **Environnement par version** : `environment.py`, lanceur, `install.sh`, `update.py`,
  redémarrage de la console ; trois tests nouveaux (création avant bascule et retour
  arrière, rattrapage d'une installation mise à jour par l'ancien code, choix de
  l'interpréteur par le lanceur).
- **Migration vérifiée sur une installation existante** (HOME jetable) : installation par
  l'`install.sh` de `main` → `ponos update` (fait par l'ancien code) vers cette branche :
  lanceur réécrit, pas de `.venv` → `ponos run` : `.venv` créé, le lanceur l'utilise,
  configuration et `ponos.db` intactes → mise à jour suivante : `.venv` créé avant la
  bascule → version qui exige un paquet introuvable : refusée, installation restée sur la
  précédente.
- `scripts/release.py` écrit et vérifie la version dans `pyproject.toml` aussi.

## 7. Front

- **`npm audit`** : 6 alertes — 1 haute (`source-map-js`, déni de service, dépendance de
  build via `@tailwindcss/node` et `@vue/compiler-sfc` : jamais servie), 5 basses
  (`dompurify`, `katex`, `remark-math`… via `@milkdown/crepe`).
- **28 paquets en retard** (mineurs pour la plupart : Radix, React 19.3, Vite 8.3) ;
  TypeScript 7 disponible (majeur, à part) ; `react-data-form` 0.1 → 0.3 et
  `react-mini-i18n` 0.1 → 0.2 (paquets maison).
- **Poids** : premier chargement **480 kB gzip** pour un budget de 500 kB dans
  `tests/run.py` (le ticket parle de 520 kB : la valeur n'est pas encore sur `main`).
  Le morceau `i18n` pèse 460 kB brut / 146 kB gzip à lui seul, le plus gros de la
  première page : à ouvrir avec un visualiseur de bundle. `vue` (et son compilateur) est
  tiré par `@milkdown/components` — hors premier chargement grâce au chargement paresseux
  de l'éditeur, mais 438 kB brut dès qu'on l'ouvre.
- **Types partagés** : aucun (voir recommandation 11).
