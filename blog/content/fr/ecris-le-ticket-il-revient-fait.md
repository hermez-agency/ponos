---
title: "Écris le ticket, il revient fait : comment Ponos fait tourner Claude Code sur ton backlog"
description: Ponos transforme un ticket passé en Prêt en session Claude Code sur un git worktree jetable, et le ramène en pull request. Voici la boucle, geste par geste.
date: 2026-11-13
tags: [Claude Code, backlog, git worktree, automatisation]
lang: fr
translation: write-the-ticket-it-comes-back-done
category: Coulisses
cover: mascot/og.png
cover_alt: Ponos, le robot, qui saute à côté de son nom et de la devise « Écris le ticket. Il revient fait. »
---

L'essentiel d'un backlog, c'est du travail qu'on sait déjà décrire. Un bug avec
une reproduction claire, une petite fonctionnalité, une dépendance à monter, un
paragraphe à réécrire. Le décrire prend deux minutes ; le faire prend un
après-midi de changements de contexte. **Ponos** est fait pour cet écart : tu
écris le ticket, une session Claude Code le fait, et il revient pour que tu le
relises.


## La boucle tient en quatre gestes

1. **Écris un ticket** sur le board de Ponos, la console, et passe-le en *Ready*.
2. **Ponos le fait.** Une session Claude Code démarre sur un `git worktree` jetable qui lui est propre, ou dans un dossier de travail quand le ticket n'a pas de dépôt.
3. **Tu relis ce qui revient**, et tu réponds en un mot s'il a posé une question, même depuis ton téléphone.
4. **Tu le passes en *Validated*.** Ponos fusionne la pull request ou publie le texte, et seulement alors le déclare *Done*.

Rien n'est fusionné ni publié tant que tu n'as pas dit oui. C'est tout le contrat.

## Un worktree par ticket

Un ticket ne touche jamais ta copie de travail. Chacun reçoit un `git worktree`
et une branche à lui, créés depuis `main`, jetés une fois le travail livré. Dix
tickets peuvent tourner côte à côte sans se marcher dessus, et ton dépôt reste
exactement comme tu l'as laissé.

```sh
git worktree list
# /home/toi/code/app                 9d54118f [main]
# /home/toi/.local/state/ponos/...   ab6a441a [ticket/fix-login-redirect]
```

> [!NOTE] Pourquoi un worktree et pas un clone
> Un worktree partage l'historique du dépôt avec ta copie : il apparaît en quelques secondes et ne coûte presque rien sur le disque. La session a un vrai dossier de travail isolé, sans seconde copie du projet.

## Pas seulement du code

Un ticket a un type, et le type décide du chemin. Un ticket de **code** revient
en pull request. Un ticket d'**écriture** revient en page rédigée dans le
ticket. Une **action externe** est menée dans un navigateur ou dans les
réglages d'un service, chaque changement consigné, avec un arrêt au premier
doute. Une **publication** est préparée, puis publiée quand tu la valides.

| Type | Ce qui revient | Ce qu'il attend |
| --- | --- | --- |
| Code | Une pull request | Ta validation, puis la fusion |
| Écriture | Une page dans le ticket | Ta validation |
| Action externe | Le journal de chaque changement | Ta lecture du journal |
| Publication | Le post, prêt | Ta validation, puis la publication |

## Un board à toi

Le board, c'est la console, et ses tickets vivent dans une base locale,
`ponos.db`. GitHub, Telegram, Slack et OpenRouter se branchent quand tu veux ;
aucun n'est obligatoire. Une question d'une session arrive sur ton téléphone, et
un mot en réponse la remet au travail.

> Le ticket est l'interface. Le reste est l'affaire de Ponos.

## À essayer sur un ticket

Prends le plus petit item de ton backlog, celui que tu repousses depuis une
semaine. Écris-le comme tu l'expliquerais à un collègue, passe-le en *Ready*, et
lis ce qui revient. La [documentation](https://github.com/hermez-agency/ponos#readme)
couvre l'installation, qui prend quelques minutes sous Linux ou macOS.
