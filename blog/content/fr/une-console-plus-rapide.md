---
title: "Une console plus rapide : des fenêtres qui s'ouvrent tout de suite, un tableau qui ne dessine que ce que tu vois"
description: Ponos 0.3 rend sa console plus rapide là où ça compte — les fenêtres, le tableau des tickets, les longues conversations et le tableau de bord — avec les temps mesurés avant et après, et les deux bibliothèques sur lesquelles elle repose désormais.
date: 2026-11-19
tags: [Ponos, console, performance, react-resource-view, react-data-form]
lang: fr
translation: a-faster-console
category: Nouveautés
cover: mascot/og.png
cover_alt: Ponos, le robot, qui saute à côté de son nom et de la devise « Écris le ticket. Il revient fait. »
---

La console de Ponos, c'est là où tu regardes le backlog bouger : un clic lent
y coûte plus qu'une page lente. La version 0.3 s'attaque aux quatre endroits
où elle l'était : les fenêtres, le tableau des tickets, les longues
conversations et le tableau de bord. Voilà ce qui a changé, et ce qu'on a
mesuré.

## Des fenêtres qui s'ouvrent tout de suite

Ouvrir un ticket, la palette ou *Nouveau ticket* figeait la page un moment.
Deux causes : les animations, et la façon dont le tableau se mettait en forme
pendant qu'une fenêtre était ouverte.

- Le panneau latéral, celui de la conversation, glisse en 200 ms au plus et se
  referme en 150 ms, au lieu de 500 et 300 ms. Aucune autre animation de sortie
  d'un composant ne dépasse 200 ms.
- Le tableau et les fenêtres n'emploient plus de sélecteurs CSS qui obligeaient
  le navigateur à recalculer le style de toute la page à chaque ouverture ou
  fermeture de fenêtre.

Sur un board de 2 000 tickets, ouvrir ou fermer une fenêtre ne laisse plus
aucune tâche de plus de 50 ms. Avant, la palette prenait 74 ms, une
conversation de 500 messages 79 ms, une fenêtre de ticket 98 ms, et la palette
sur la liste des tickets 2,9 s à l'ouverture, avec quatre tâches d'une seconde
à la fermeture. La toute première ouverture de *Nouveau ticket* reste à 54 à
64 ms, contre 105 ms avant : c'est la première création de l'éditeur Markdown,
payée une seule fois.

## Un tableau qui ne dessine que ce que tu vois

Le tableau des tickets vient désormais de `react-resource-view` 2.1, qui ne
dessine que les lignes à l'écran. Sur un board de 2 000 tickets, la page
porte 814 nœuds au lieu de 57 625. Un test refuse dans la feuille de style
construite les sélecteurs qui provoquaient ces recalculs, pour qu'ils ne
reviennent pas en silence.

## Le tableau de bord ne se fige plus

Sur un board de 2 266 tickets, chaque mouvement du tableau pendant qu'un ticket
tournait bloquait la page : 850 à 900 ms de script dans le gestionnaire de mise
à jour du flux, puis 640 à 710 ms de rendu, mesurés sur une machine lente
(CPU ×4). Maintenant, un ticket inchangé garde sa ligne, sa carte n'est plus
redessinée, et le travail se fait par morceaux. Le même mouvement prend 60 à
100 ms à ×4, en morceaux, et on n'a relevé aucune frame de plus de 50 ms sur
une minute sans ralentissement.

## Une longue conversation reste agréable à écrire

Une conversation de 120 messages faisait attendre chaque frappe : le champ de
réponse mesurait sa hauteur à chaque touche, et chaque message était redessiné
à chaque morceau d'une réponse. Maintenant :

- le champ grandit par `field-sizing: content`, la fonction du navigateur là où
  elle est comprise (Chrome, Edge) : 34 ms par frappe sont tombées à 1 ms sur
  cette conversation ;
- les messages hors de l'écran ne sont plus mis en page, et un message déjà
  affiché n'est plus redessiné ;
- une conversation s'ouvre sur ses 60 derniers messages, et le bouton
  « Afficher les précédents » en ajoute 60 sans faire sauter ta lecture.

Un test du navigateur échoue désormais si une frappe dans une conversation de
500 messages dépasse 16 ms.

## Un premier chargement plus léger, et une palette qui répond

La première page de la console en français passe de 508 à 455 Ko compressés :
les mots des réglages et de la première connexion arrivent avec elle, et les
pages qui en ont besoin de plus (un ticket, un projet, les idées) les chargent
quand elles s'affichent.

La palette Ctrl+K filtre elle-même ses entrées au lieu de laisser la
bibliothèque classer chaque ticket du board. Sur un board de 1 848 tickets, le
délai d'interaction en tapant cinq lettres passe de 1 208–1 288 ms à 88–152 ms.

## Les deux bibliothèques dessous

- **react-resource-view** — la console passe de la 0.6 à la 2.1. La branche 2.x
  apporte le tableau virtualisé ; la colonne d'actions collée, corrigée en 2.0,
  en fait partie.
- **react-data-form** — sur la 0.3. Ses formulaires sont habillés par
  `index.css` de la console, avec les sélecteurs coûteux réécrits : la largeur de
  barre de défilement retirée de la page n'est plus héritée par chaque élément,
  et la page derrière une fenêtre cesse d'être restylée d'un bloc.

Rien ne change dans ta façon d'utiliser la console : le même board, les mêmes
raccourcis, les mêmes fenêtres, seulement plus vite à ouvrir et à remplir.

## Essaie

Mets Ponos à jour en 0.3.0 avec ta commande habituelle, ouvre un board de
quelques centaines de tickets, puis la palette et une fenêtre de ticket l'une
après l'autre. Le [guide de la console](https://github.com/hermez-agency/ponos/blob/main/guide/console.md)
décrit les vues, et le [guide d'installation](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md)
couvre la mise à jour.

*Un produit Hermez.*
