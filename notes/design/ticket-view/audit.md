# La vue d'un ticket — audit, directions, refonte

Novembre 2026. La vue d'un ticket dans la console, ouverte en fenêtre au-dessus
du tableau (`record-window.tsx`, `ticket-window.tsx`) ou en page complète
(`ticket-page.tsx`) : ce qui n'allait pas, les trois directions pesées, celle
qui a été retenue et implémentée.

> Ce dossier est dans `notes/` et non dans `docs/design/` comme le ticket le
> demandait : `docs/` est le site public (the-ponos.app), tout fichier posé là
> est servi, et un test de `tests/test_release.py` refuse un `.md` ou un dossier
> inconnu sous `docs/`.

Les captures sont prises sur la console de démo (`scripts/demo.py`) : un ticket
de code en cours avec sa session en direct, un ticket de code en revue avec sa
PR et une CI rouge, un ticket bloqué sur une question — bureau 1440 × 900 et
téléphone 390 × 844, en fenêtre et en page. `before/` est `main`, `after/` est
cette branche.

## 1. Audit

La question posée à chaque capture : quelqu'un qui ouvre ce ticket veut savoir
**où il en est** et **s'il a quelque chose à faire**. En combien de temps la vue
le dit-elle ?

### Gravité haute — on ne trouve pas ce qu'on est venu chercher

| # | Constat | Où |
|---|---------|----|
| H1 | **Le statut est le cinquième mot d'une bande de métadonnées**, au même poids que « created 3d ago », entre la priorité et la date. Rien dans la vue ne dit en premier où en est le ticket ; la couleur de la colonne, qui porte tout le tableau, se réduit à un point de 6 px. | fenêtre et page |
| H2 | **L'action principale est un onglet à trouver.** En revue, « Décider » est le cinquième onglet sur six, avec un pictogramme rose de 16 px ; le seul bouton de la vue est un « … ». En cours, « Pause » et « Abandonner » sont deux boutons jumeaux au bout de la ligne des onglets. | fenêtre et page |
| H3 | **Sur téléphone, les onglets n'arrivent qu'à 550 px de haut sur 844, et le cinquième est coupé au bord** (« Dec »). Avant eux : le retour, le titre sur deux lignes, l'identifiant, un lien « pull request », une ligne « Your decision is awaited » — un rattrapage propre au téléphone pour H2 —, la bande de faits sur quatre lignes, la CI. Les gestes du ticket passent sur une ligne à eux, sous les onglets. | page mobile |
| H4 | **La pull request est dite trois fois, sa CI deux fois** : « pull request ↗ » dans l'en-tête de la page, « PR #391 » dans la bande, « PR #391 » encore dans l'onglet Résultat avec « CI failed », déjà dépliée juste au-dessus. Trois liens vers la même adresse, et aucun des trois ne ressemble à l'endroit où la PR se lit. | page ; deux fois en fenêtre |

### Gravité moyenne — on trouve, mais on relit

| # | Constat | Où |
|---|---------|----|
| M1 | **La bande de faits n'a pas de noms.** « $8.13 opus worked 38 min 12 s last session 38 min » : sept valeurs à la suite, à deviner. Session et machine sont derrière un « … » de 12 px, sans nom non plus. | fenêtre et page |
| M2 | **Six onglets de natures différentes** : deux contenus (Résultat, Mission), une conversation, deux journaux (Direct, Journal), une action (Décider). « Direct » n'a rien de direct sur neuf tickets sur dix ; « Journal » et « Direct » racontent la même chose à deux échelles et se renvoient l'un à l'autre. | fenêtre et page |
| M3 | **Fenêtre et page ne disent pas la même chose dans leur en-tête.** La fenêtre : l'identifiant au-dessus du titre, et l'objectif. La page : l'identifiant dessous, pas d'objectif, mais deux liens (pull request, session) que la fenêtre n'a pas. | fenêtre contre page |
| M4 | **À l'ouverture de la fenêtre, le focus est sur le choix de l'objectif** : un anneau orange autour d'un réglage secondaire, qui passe pour l'élément principal de la fenêtre — et une flèche du clavier change l'objectif du ticket. | fenêtre |
| M5 | **La cause d'un blocage est en petit** : une puce « Question for you » de 11 px et une ligne grise de 12 px, sous la bande de faits. C'est pourtant la seule chose de la vue sur laquelle on peut agir. | fenêtre et page |
| M6 | **Sur une page de 1440 px, tout tient dans la moitié gauche** d'une colonne de 1088 px ; la moitié droite est vide, pendant que les faits s'entassent sur une ligne. | page bureau |

### Gravité basse — à l'occasion

| # | Constat | Où |
|---|---------|----|
| B1 | L'état « en direct » est dit trois fois (le point de l'onglet, « writing now · 7 steps », « writing now · thinking… ») mais jamais dans le statut : la bande dit « In progress », sans la phase. | en cours |
| B2 | La bande de faits n'a aucune sémantique (des `span` séparés par des « · ») : un lecteur d'écran lit une phrase sans verbes. La cible du « … » fait 12 px. | accessibilité |
| B3 | « Pause » et « Abandonner » ont le même poids, côte à côte, alors que l'un garde le travail et l'autre le perd. *Non traité ici* : les gestes d'un ticket en cours (`ticket-stop.tsx`) restent tels quels, voir « Ce qui reste ». | en cours |
| B4 | Rapidité d'ouverture : rien à redire depuis #b352df29 (page différée d'un rendu, `content-visibility`, animations à 200 ms). Rien n'y est touché. | fenêtre |

### Les captures d'avant

| | Fenêtre, bureau | Page, bureau | Page, téléphone |
|---|---|---|---|
| En revue | ![](before/review-window-desktop.png) | ![](before/review-page-desktop.png) | ![](before/review-page-mobile.png) |
| En cours | ![](before/running-window-desktop.png) | ![](before/running-page-desktop.png) | ![](before/running-page-mobile.png) |
| Bloqué | ![](before/blocked-window-desktop.png) | ![](before/blocked-page-desktop.png) | ![](before/blocked-page-mobile.png) |

## 2. Trois directions

Dessinées en filaire dans VectorCraft (Claude Design n'était pas accessible
depuis la session) : `directions.svg` est la source, `directions.png` son
export.

![Les trois directions](directions.png)

| | A — Bandeau d'état | B — Deux colonnes | C — Fil unique |
|---|---|---|---|
| L'idée | Le statut, ce qu'il attend et l'action principale d'abord ; les faits repliés ; moins d'onglets. | Le contenu à gauche, un rail de propriétés et d'actions à droite, comme une issue GitHub ou Linear. | Plus d'onglets : mission, sessions, questions et résultat dans un seul fil daté, l'action collée en bas. |
| Répond à | H1, H2, H3, H4, M2, M5 | M1, M6, H4 | H2, M2 |
| Pour | Même réponse en fenêtre, en page et sur téléphone. | Tous les faits visibles et nommés ; bon usage d'une page large. | Raconte le ticket dans l'ordre ; l'action sous le pouce. |
| Contre | Les faits rares demandent un clic en fenêtre. | En fenêtre (768 px) le rail prend un tiers au résultat ; le statut redevient une propriété parmi d'autres ; sur téléphone tout est replié. | Un ticket à cinq sessions devient une page sans fin ; plus d'adresse par onglet ; réécrit discussion, direct et décision. |

**Retenue : A, avec le rail de B là où il a la place.** Le bandeau d'état
répond aux quatre constats graves et se dessine pareil partout. Le rail de B ne
vaut que sur une page large — exactement là où A laisse la moitié de l'écran
vide (M6) : la liste des faits y devient une colonne à côté des onglets, et
reste une ligne avec « Détails » en fenêtre et sur téléphone. C'est une seule
liste, dessinée de deux façons selon la place (une media query lue par la page,
pas des règles de plus dans la feuille de style du premier chargement, tenue à
un budget). C est écartée : elle casse les
adresses par onglet et les parcours de la discussion et de la décision, pour un
gain que le bandeau apporte déjà.

## 3. La direction retenue, en détail

Trois blocs au-dessus des onglets, les mêmes en fenêtre et en page
(`frontend/src/components/console/ticket-status.tsx`) :

1. **Le statut** (`TicketStatus`) — la colonne en toutes lettres, dans sa
   couleur de tableau (fond et bord du bandeau) ; une phrase sur ce que le
   ticket attend (« Votre décision est attendue. », « Une session travaille
   dessus. » ou la phase du run, la cause d'un blocage avec son pictogramme et
   sa ligne d'aide) ; et les gestes du ticket, au même endroit — celui qu'il
   attend en bouton plein (Décider, Débloquer), les autres en contour ou
   derrière « … ».
2. **Les faits** (`TicketFacts`) — une liste de définitions : projet, type,
   priorité, coût, modèle, temps travaillé, puis dernière session, estimation,
   création, branche, session, machine. Repliée : une ligne des six premiers,
   sans noms, et « Détails ». Dépliée, ou d'office en colonne à droite sur une
   page d'au moins 1280 px : chaque fait sous son nom.
3. **La livraison** (`TicketDelivery`) — la pull request, une fois : son
   numéro, où elle en est, ses checks un par un, « Voir le diff ».

Puis les onglets, cinq au plus au lieu de six : **Décider** (en revue
seulement, en premier ; sur téléphone il ne se dessine qu'une fois ouvert, le
bouton du bandeau y mène), **Résultat**, **Mission**, **Discussion**,
**Activité** — la session et le journal réunis, la session d'abord quand elle
tourne, le journal d'abord sinon.

L'en-tête de la page porte l'objectif sous le titre, comme celui de la fenêtre ;
la fenêtre prend elle-même le focus à l'ouverture.

En français, et l'onglet Décider ouvert depuis le bouton du bandeau sur
téléphone (il n'y est dessiné qu'une fois ouvert ; Activité est alors à un
glissement de la liste) :

| Page en revue, en français | Fenêtre en revue, onglet Décider, téléphone |
|---|---|
| ![](after/review-page-desktop-fr.png) | ![](after/review-window-mobile-decide.png) |

### Fenêtre

| | Bureau | Téléphone |
|---|---|---|
| En cours | ![](after/running-window-desktop.png) | ![](after/running-window-mobile.png) |
| En revue, avec PR | ![](after/review-window-desktop.png) | ![](after/review-window-mobile.png) |
| Bloqué | ![](after/blocked-window-desktop.png) | ![](after/blocked-window-mobile.png) |

### Page

| | Bureau | Téléphone |
|---|---|---|
| En cours | ![](after/running-page-desktop.png) | ![](after/running-page-mobile.png) |
| En revue, avec PR | ![](after/review-page-desktop.png) | ![](after/review-page-mobile.png) |
| Bloqué | ![](after/blocked-page-desktop.png) | ![](after/blocked-page-mobile.png) |

## 4. Ce qui change pour qui s'en sert

| Avant | Après |
|---|---|
| Statut : un point et un mot dans la bande | Bandeau en tête, dans la couleur de la colonne, avec ce que le ticket attend |
| Décider : un onglet, plus une ligne rose sur téléphone | Bouton plein dans le bandeau ; l'onglet en premier |
| Gestes au bout de la ligne des onglets | Dans le bandeau, à côté du statut |
| Cause du blocage : puce de 11 px sous la bande | Dans le bandeau, sous « Bloqué » |
| PR dans l'en-tête, la bande et le Résultat ; CI au-dessus des onglets et dans le Résultat | Un bloc, au-dessus des onglets |
| Faits sans noms ; « … » pour session et machine | Liste nommée ; « Détails », ou colonne sur page large |
| Onglets Direct et Journal | Un onglet Activité (`&tab=live` ; `&tab=journal` y mène) |
| Objectif en fenêtre seulement | En fenêtre et en page |

### Ce qui part, dit clairement

- La ligne « Your decision is awaited » propre au téléphone
  (`ticket-decide-cue`) : le bandeau dit la même chose partout.
- Les liens « pull request ↗ » et « session ↗ » de l'en-tête de la page : la PR
  a son bloc, le lien de session est dans les faits, à côté de l'identifiant de
  session.
- La carte de PR dans l'onglet Résultat : un ticket de code sans résultat écrit
  y dit « sa pull request, ci-dessus, est le résultat », suivi de ce que la
  session dit avoir changé.
- L'onglet Journal en tant qu'onglet, et son adresse `&tab=journal` (qui ouvre
  Activité).

Rien d'autre ne disparaît : résultat et versions, mission, validation, prompt
« On », discussion et réponses rapides, décision, session en direct, journal,
historique de qui a fait quoi, choix du projet d'un ticket bloqué, raison d'une
attente en *Ready*, note du passage précédent.

## 5. Ce qui reste

- **B3** — « Pause » et « Abandonner » de même poids sur un ticket en cours.
- Le bandeau n'est pas collant : sur une longue discussion, il sort de l'écran
  avec le reste. Un bandeau réduit qui reste en haut de la fenêtre se discute.
- Le pourcentage d'avancement d'un run (le plan de l'agent) est sur la carte et
  dans l'onglet Activité, pas dans le bandeau.
