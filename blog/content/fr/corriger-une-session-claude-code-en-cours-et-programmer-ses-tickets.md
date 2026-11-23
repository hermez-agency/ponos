---
title: "Corriger une session Claude Code en cours, la reprendre à n'importe quelle étape, programmer ses tickets : les nouveautés de Ponos"
description: Corrige une session Claude Code pendant qu'elle travaille, relance un ticket depuis l'étape où il s'est trompé, date tes tickets sur un agenda et pose des règles que l'agent ne peut pas ignorer — ce qui a été fusionné sur le main de Ponos cette semaine.
date: 2026-11-23
tags: [Ponos, Claude Code, agents IA, garde-fous, planification, backlog]
lang: fr
translation: steer-a-running-claude-code-session-and-schedule-tickets
category: Nouveautés
---

La dernière mise à jour parlait de vitesse : une console qui ouvre ses fenêtres
tout de suite. Celle-ci parle de contrôle. Jusqu'ici, une fois un ticket lancé,
tu avais deux choix : laisser la session finir, ou l'arrêter. Depuis, une série de
changements fusionnés sur `main` t'apporte les moments entre les deux — dire
quelque chose à l'agent pendant qu'il travaille, le ramener à l'étape où il a
dévié, décider *quand* il démarre — et quelques règles qu'il ne peut pas
contourner.

Si tu ne le connais pas encore : **Ponos** transforme un ticket passé en *Ready*
en session Claude Code sur un `git worktree` jetable, et le rend sous forme de
pull request ou de page rédigée. Voici ce qui a changé, regroupé par ce que ça
change pour toi plutôt que par pull request.

## Corriger un ticket pendant qu'il tourne

Tu ouvres un ticket en cours, tu lis son journal en direct, et tu vois l'agent
partir vers le mauvais fichier. Avant, un commentaire attendait le passage
suivant. Désormais, un message envoyé à un ticket **dont la session tourne est
donné à l'agent**, depuis la vue du ticket dans la console, ou depuis Telegram et
Slack quand tu réponds sur le ticket. Il y a deux façons de le dire :

- **Une correction** (par défaut) — *« non, pas ce fichier »*. Elle est remise à
  la fin de l'appel d'outil en cours, et la session n'est pas arrêtée.
- **Un message pour la suite** — coche la case qui le garde pour la fin dans la
  console, ou commence un message de canal par `après`. Il attend que l'agent
  s'apprête à clore la session, qui continue alors avec lui avant d'écrire son
  rapport.

Les deux apparaissent dans le journal du ticket comme une étape *Message*, à leur
place parmi ce que l'agent a fait : le récit se lit dans l'ordre. Derrière, ce
sont deux hooks de Claude Code que Ponos ajoute à la session du ticket. Un message
que la session n'a pas lu avant de se terminer n'est pas perdu : il devient un
commentaire, que le passage suivant lit.

## Repartir de l'étape où ça a déraillé

Parfois, c'est la douzième étape sur trente qui a mal tourné, et tout ce qui suit
n'est que du bruit. Relancer le ticket entier jette les onze bonnes étapes ;
reprendre la session emporte l'erreur avec elle. Il y a maintenant une troisième
voie.

Dans le journal du ticket, vise une étape — une phrase de l'agent ou un appel
d'outil — et clique sur **Relancer depuis ici**. Tu peux ajouter un message
(*« cette fois, utilise la fonction qui existe déjà »*), et le ticket repasse en
*Ready*. Sa prochaine session **connaît la conversation jusqu'à cette étape, et
rien après**, puis s'ouvre sur ton message. C'est un nouveau run : celui d'où il
part reste lisible tel quel, et le journal montre de quelle étape de quel run
chaque branche est partie.

Une chose à savoir avant de t'en servir : **les fichiers ne sont pas remis en
arrière**. Seule la conversation est rembobinée ; le worktree et la branche du
ticket restent tels que la session précédente les a laissés. La fenêtre de
confirmation le dit, et la nouvelle session aussi l'apprend : elle lit
`git status`, l'historique et le diff avant d'écrire, et défait ce qui ne colle
pas. Pour repartir de fichiers propres, relance le ticket depuis le début.

## Pause n'est pas Abandonner

Sur un ticket en cours, *Pause* et *Abandonner* étaient deux boutons jumeaux, côte
à côte — l'un garde tout, l'autre jette la session et le travail non poussé.
**Pause** reste un bouton, au même endroit. **Abandonner** passe dans le menu
« … » à côté, en rouge, et sa fenêtre dit ce qui est perdu et s'ouvre sur
*Annuler* : un Entrée réflexe n'abandonne plus rien.

## Programmer un ticket pour plus tard, et le voir sur un agenda

Le runner respectait depuis longtemps la date `Scheduled` d'un ticket. Tu peux
maintenant la poser partout où tu écris un ticket :

- dans la console, un champ **Programmé pour** dans *Nouveau ticket*, avec des
  raccourcis — *dans 1 h*, *ce soir*, *demain matin*, *lundi prochain* — ou une
  date et une heure dans le fuseau de ton navigateur ; la vue d'un ticket la
  change ou la retire tant qu'il n'est pas terminé, et **Lancer maintenant** la
  retire ;
- depuis Claude, avec `scheduled` dans l'outil `create_task` du MCP ;
- depuis un terminal, `ponos schedule PON-142 "demain 9h"` ou
  `ponos move PON-142 ready --at +2h`.

Une date passée est refusée plutôt que lue comme *maintenant* : une date tapée
avec un jour d'erreur ne doit pas lancer une session payante sans qu'on le voie.
Pour voir ce qui arrive, le board gagne une troisième vue à côté de **Colonnes**
et **Liste** : **Agenda**, un calendrier à la semaine, au jour ou au mois où
chaque ticket daté est posé à son heure, et où les prochains passages de tes
récurrences actives apparaissent à côté, marqués ↻. Sur la *Liste*, **Champs
affichés** masque les colonnes que tu ne lis pas.

## Des règles que l'agent ne peut pas ignorer

Un prompt peut demander à une session de ne pas toucher à ton fichier de licence ;
une session peut l'oublier. Ponos vérifie désormais chaque appel d'outil **avant
qu'il ne s'exécute**, avec un hook `PreToolUse` de Claude Code, contre une table
`[guards]` — dans `config.toml`, et dans le `.ponos.toml` propre à un projet :

```toml
# .ponos.toml, à la racine du dépôt
[guards]
read_only = ["LICENSE", "**/package.json"]
forbidden = [".env", "secrets/**"]
commands = ["terraform\\s+destroy"]
```

Un chemin peut être en lecture seule ou interdit tout court, les commandes sont
des expressions régulières, et trois gestes git — un push sur la branche de base,
un push forcé, la suppression d'une branche — sont refusés sauf si tu les
autorises. L'agent reçoit la raison et change de méthode ; le refus devient une
ligne *Guard* dans le journal du ticket, et les réglages du projet listent les
règles et les derniers refus. C'est un filet, pas une prison : le hook repère les
façons courantes d'écrire un fichier, pas les cent.

## Emporter ton Ponos, jamais le coffre

**Réglages → Export & import** (ou `ponos export` et `ponos import`) écrit tout
ce que Ponos garde dans un seul zip : réglages, projets, contexte, mémoires,
objectifs, récurrences, skills, tickets avec leurs journaux — et, seulement si tu
les coches, les conversations. Le coffre-fort et tous les secrets ne sortent
jamais ; l'archive liste leurs *noms*, pour que tu saches quoi ressaisir. Un
import montre d'abord un aperçu, puis fusionne ou remplace après confirmation et
une copie de la base. Rien ne démarre à l'arrivée : les tickets en cours
reviennent en brouillon, les récurrences reviennent désactivées.

Le coffre lui-même devient plus aimable : il se déverrouille **une fois** avec le
mot de passe de la console, et se reverrouille après quinze minutes sans action,
au lieu de redemander le mot de passe dans chaque formulaire.

## Un board qui se lit plus vite

Des changements plus petits, que tu croiseras tous les jours :

- **Un id court par ticket** : `PON-142`, numéroté par projet et affiché après le
  titre. Un clic le copie, et la CLI, l'API et le MCP l'acceptent partout où l'on
  désigne un ticket.
- **La relecture, dite en question** : le réglage qui s'appelait *Force
  validated* s'appelle *Relecture*, avec *Selon le projet*, *Jamais* et
  *Toujours*. Une récurrence peut le régler pour les tickets qu'elle crée.
- **Une vue de ticket en deux colonnes** sur grand écran : les onglets à gauche,
  un rail à droite avec le statut et son geste principal, les faits modifiables
  sur place, et la pull request dite une seule fois.
- **Une barre de filtres qui se replie** : la recherche, *Projet*, *Statut* et
  *Priorité* restent à portée ; le reste passe derrière un bouton **Filtres**, et
  les filtres actifs s'affichent en pastilles.
- **Un seul bandeau quand aucun démon ne tourne**, avec la commande qui le
  démarre, au lieu d'une alerte sur chaque carte prête.
- **Les conversations de la console replient leurs étapes** en une ligne au titre
  clair.

## Quand en profiter

Tout cela est fusionné sur `main` et listé sous *Unreleased* dans le changelog ;
ça arrive sur ton installation avec la prochaine version. Le guide décrit déjà
chaque partie : [corriger un ticket en cours](https://github.com/hermez-agency/ponos/blob/main/guide/tickets.md#correcting-a-ticket-while-it-runs),
[repartir d'une étape](https://github.com/hermez-agency/ponos/blob/main/guide/tickets.md#starting-again-from-one-step-of-a-session),
[les garde-fous](https://github.com/hermez-agency/ponos/blob/main/guide/safety.md#what-protects-your-code)
et [l'export et l'import](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md#export-and-import).

## Essaie

Le [guide d'installation](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md)
prend quelques minutes sous Linux ou macOS. Écris un petit ticket, passe-le en
*Ready* et, pendant qu'il tourne, ouvre son journal et envoie-lui une correction
d'une ligne. Puis date le suivant pour demain matin, et retrouve-le sur l'Agenda.

*Un produit Hermez.*
