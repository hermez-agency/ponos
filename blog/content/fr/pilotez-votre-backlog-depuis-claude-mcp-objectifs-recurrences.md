---
title: "Pilotez votre backlog depuis Claude : le MCP de Ponos gère maintenant projets, objectifs et récurrences"
description: Le connecteur MCP de Ponos crée désormais projets, objectifs et récurrences, rattache des tâches à un objectif et les lance après un aperçu du coût — par les règles de la console, sans jamais rien supprimer.
date: 2026-11-16
tags: [MCP, Claude Code, backlog, automatisation, objectifs]
lang: fr
translation: drive-your-backlog-from-claude-mcp-goals-recurrences
category: Nouveautés
---

Il y a une semaine, le connecteur MCP de Ponos savait lire votre board et écrire
un ticket en brouillon. Cette semaine, il sait le mettre en place. Voici ce qui a
été fusionné sur `main` depuis le dernier article, regroupé par ce que cela change
pour vous plutôt que par pull request.

Si vous ne connaissez pas encore : **Ponos** transforme un ticket passé en *Prêt*
en session Claude Code sur un `git worktree` jetable, et le ramène en pull request
ou en page rédigée. Le connecteur [MCP](https://modelcontextprotocol.io) est la
porte par laquelle Claude (claude.ai, Claude Desktop ou Claude Code) parle à votre
board.

## Votre assistant peut maintenant organiser le board

Jusqu'ici, créer un projet, un objectif ou une récurrence demandait d'ouvrir la
console. Quatre groupes d'outils changent cela, et tous passent par **le circuit
de la console elle-même** : mêmes noms à vérifier, mêmes validations, mêmes
erreurs. Un client n'a pas de porte dérobée.

- **Projets** — `create_project` et `update_project`. Indiquez un dossier git déjà
  présent sur la machine, donnez un `owner/name` GitHub que Ponos clonera, ou
  créez un projet document sans dépôt. Un nom pris, un dossier absent ou un clone
  raté est refusé, et rien n'est laissé à moitié fait.
- **Objectifs** — `create_goal` et `update_goal` : un nom, un critère, une
  échéance, une priorité de 0 à 100 et les projets concernés. Un objectif peut
  être désactivé ; il ne peut pas être supprimé d'ici.
- **Rattacher des tâches à un objectif** — `set_task_goal` rattache des tâches
  existantes à un objectif, ou les en détache. Tout est vérifié avant d'écrire :
  une tâche inconnue refuse tout le lot, et la réponse donne l'objectif de chaque
  tâche avant et après.
- **Récurrences** — `list_schedules`, `create_schedule` et `update_schedule`.

Vous pouvez dire, en conversation : *« Crée un projet pour le dépôt
`acme/billing`, un objectif "Livrer la facturation avant décembre", et rattache
ces quatre tickets. »* Claude le fait en quelques appels, et vous relisez le
résultat sur le board.

## Une récurrence ne s'allume jamais toute seule

Une récurrence est ce qu'il y a de plus risqué à confier à un assistant : elle crée
des tickets d'elle-même, à heure fixe, et chacun peut démarrer une session payante.
La règle est donc nette.

> Une récurrence écrite par un client naît **toujours désactivée**. Aucun outil ne
> l'active, ne la lance ni ne la supprime.

La console la marque **À relire** et propose un bouton *Activer*. Vous lisez la
mission, la cadence et le type, puis vous appuyez vous-même. C'est la même
posture que pour le reste du connecteur : un ticket créé par un client est un
brouillon, et rien ne supprime de données.

## Une récurrence peut servir un objectif

Les récurrences ont reçu cette semaine un champ à elles : **Objectif**. Une
récurrence qui sert un objectif y rattache chaque ticket qu'elle produit, qu'il
naisse à l'heure dite ou par *Lancer maintenant*. La barre de progression de
l'objectif — *n tickets sur m terminés* — compte alors aussi le travail
récurrent, au lieu de le laisser de côté.

Si vous avez un bump de dépendances ou un rapport hebdomadaire, c'est le chaînon
manquant : l'objectif « Garder le produit en bonne santé » reflète enfin les
corvées qui l'y maintiennent. Un objectif terminé ou supprimé n'arrête pas la
récurrence ; ses tickets naissent simplement sans objectif.

## Lancer, avec le prix affiché

`launch_task` permet à l'assistant de passer des tickets en *Prêt*, ce qui démarre
des sessions payantes. Il fonctionne volontairement en deux appels. Sans
`confirm`, rien ne change et vous obtenez un **aperçu** : les tâches retenues, avec
projet, modèle et coût estimé, et celles refusées, avec la raison. Ce n'est
qu'après votre « oui » explicite que le second appel, avec `confirm: true`, les
lance. Chaque lancement est écrit dans l'historique du ticket au nom du client. Si
vous préférez garder ce geste pour vous, désactivez *L'assistant peut lancer des
tickets* dans les réglages.

## Une page de ticket plus lisible

Deux changements dans la console que vous verrez chaque jour :

- La page du ticket sépare la **Mission** et le **Résultat** en deux onglets.
  *Mission* est toujours là ; *Résultat* n'apparaît qu'une fois le travail fini,
  donc la page d'un ticket en cours n'affiche plus de case vide.
- Le prompt **On**, que Ponos exécute à chaque changement de statut, était caché
  sous le journal. Il a maintenant son champ à la création et sa section dans
  l'onglet Mission, et il s'écrit aussi depuis le MCP.

## Des commits plus propres, un disque qui reste raisonnable

Deux changements plus discrets, tous deux affaire de confiance :

- **Les sessions ne signent plus commits et pull requests comme Claude.** Plus de
  ligne `Co-Authored-By`, plus de pied « generated with » — sauf si vous activez le
  réglage `claude.attribution`. Votre historique est le vôtre.
- **Journaux rotatifs.** Le dossier `logs/` ne dépasse jamais `runner.log_max_mb`
  (4 Go par défaut, réglable). Au-delà, les plus anciens journaux de session
  partent d'abord. Un runner qui vit sur votre machine toute l'année ne doit pas
  la grignoter.

Ponos ne commite en outre plus de fichiers propres à un outil d'agent dans vos
dépôts : les instructions vivent dans `AGENTS.md`, et un worktree qui n'a que lui
reçoit un `CLAUDE.md` d'une ligne, jamais commité, qui y renvoie.

## À essayer

Connectez Ponos à Claude une fois — *Réglages → Connecteurs → Ajouter un
connecteur personnalisé* avec `https://<votre console>/mcp`, puis **Connecter** —
et demandez *« qu'est-ce qui m'attend ? »*. Demandez ensuite un objectif et une
récurrence, puis ouvrez la console pour relire ce que Claude a préparé. Rien de ce
qu'il crée n'est activé sans vous.

Le [guide d'installation](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md)
prend quelques minutes sous Linux ou macOS, et la
[section MCP du guide de la console](https://github.com/hermez-agency/ponos/blob/main/guide/console.md#connect-ponos-to-claude)
liste chaque outil et ce qu'il a le droit de faire.

*Un produit Hermez.*
