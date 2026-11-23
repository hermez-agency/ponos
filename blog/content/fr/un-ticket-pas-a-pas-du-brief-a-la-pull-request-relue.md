---
title: "Un ticket pas à pas : du brief écrit à la pull request relue, avec Claude Code"
description: Un exemple suivi sur un board de démonstration — comment écrire un ticket que Claude Code peut finir seul, ce que Ponos fait pendant la session, ce que la relecture automatique attrape, et le seul geste qui livre.
date: 2026-11-23
tags: [Ponos, Claude Code, pull request, relecture, git worktree, cas d'usage]
lang: fr
translation: one-ticket-step-by-step-from-brief-to-reviewed-pull-request
category: Cas d'usage
---

La plupart des articles sur Claude Code appliqué à un backlog restent
abstraits. Celui-ci suit un seul ticket, de la première ligne que tu tapes à
la pull request que tu fusionnes, sur un board de démonstration aux données
inventées : aucun vrai projet, aucun vrai client. Le ticket est petit et
ordinaire — *Rate limit the search endpoint* — précisément le genre de
travail dont un backlog est plein.

## 1. Écris un brief qu'un agent peut finir seul

Une session travaille sans personne à qui demander, donc le ticket doit
porter ce que tu dirais à voix haute. Celui de l'exemple a un court contexte,
puis deux listes :

- **À faire** : signaler dans le rapport tout ce que la session n'a pas pu
  vérifier ; ne pas toucher aux noms publics, que d'autres projets importent ;
  traiter le cas vide et le cas d'une valeur très longue ; garder le
  changement dans le module, sans ménage au passage.
- **Critère de fin** : le nouveau comportement est couvert par un test qui
  était rouge avant ; rien en dehors du périmètre du ticket n'est modifié ; la
  suite existante est verte et le linter n'a rien à dire.

![Un ticket en relecture dans la console de Ponos : son brief avec les listes « What to do » et « Done when », sa pull request, son coût et ses checks.](console/ticket-light.webp "La page du ticket sur le board de démonstration : le brief, en bas, est la seule partie de la page que la session reçoit.")

Pourquoi la seconde liste compte : un critère de fin se vérifie contre le
diff. Ponos le lit en premier au moment de relire le travail (on y vient plus
bas) : un ticket flou reçoit une relecture floue, un ticket précis une
relecture précise.

Tu choisis un type, ici *Code* avec le sous-type *Security*, un score de
priorité (40) et, si tu veux, un modèle. Puis tu fais passer le ticket de
*Draft* à **Ready**. Ce geste-là déclenche le travail.

## 2. La session tourne dans son propre worktree

Au prochain passage du démon, le runner réclame le ticket : il passe en *In
progress*, et Ponos crée un `git worktree` jetable sur une branche à lui.
Ta copie de travail, tes fichiers non commités et ta branche courante restent
exactement comme tu les as laissés, et deux tickets du même dépôt peuvent
avancer en même temps.

Sur le board, la carte d'un ticket en cours montre ce que l'agent est en train
d'éditer, son coût jusque-là et deux boutons, *Pause* et *Abandon*. Dans la
vue du ticket, l'onglet *Live* diffuse la session pas à pas.

![Le board : brouillons, tickets prêts et tickets en cours, chaque carte avec sa priorité, son modèle et son projet.](console/board-light.webp "Le board de démonstration. Déposer une carte dans une autre colonne prévient le runner.")

Tu n'as pas à regarder, mais tu peux corriger. Un message envoyé à un ticket
dont la session tourne est remis à l'agent après l'appel d'outil en cours :
« non, pas ce fichier » marche, et la session n'est pas arrêtée. Écrit comme
message pour plus tard, il attend que l'agent ait fini ce qu'il faisait. Si
une session a pris un mauvais virage à sa douzième étape sur trente, tu peux
aussi relancer une nouvelle session depuis cette étape, avec un message de
ton cru : la conversation est rembobinée, pas les fichiers, et la nouvelle
session en est prévenue.

## 3. Des règles que l'agent ne peut pas oublier

Un prompt s'oublie ; un refus, non. Avant chaque appel d'outil, un hook de
Claude Code confronte l'appel aux garde-fous du projet : chemins en lecture
seule ou interdits, motifs de commandes, et trois gestes git (un push sur la
branche principale, un push forcé, la suppression d'une branche) refusés tant
que tu ne les as pas autorisés. L'agent en connaît la raison et change de
voie ; le refus est écrit dans le journal du ticket.

Et l'agent commit, mais il ne publie pas. Pousser une branche et ouvrir une
pull request sont des gestes qui sortent de la machine : le runner les fait
ensuite, une fois établi qu'il y a bien des commits.

## 4. Une seconde lecture avant celle de quelqu'un d'autre

Quand la session a commité, et avant tout push, une seconde session, courte,
lit la branche en mode plan, où elle ne peut rien écrire. Elle reçoit le
ticket, le `AGENTS.md` ou le `CLAUDE.md` du projet et le diff, et cherche ce
qu'une lecture contre le ticket trouve en une minute : un test demandé et
pas écrit, un fichier généré non régénéré, un critère de fin rempli en
paroles seulement. Le style n'est pas son affaire.

Si elle soulève des points, la session du ticket est reprise une fois pour
corriger ce dont elle convient et dire, point par point, ce qu'elle a corrigé
et ce qu'elle a laissé. La pull request s'ouvre quoi qu'il arrive, avec une
section **Review** qui liste tout cela. Ta propre relecture, qui vient
après, part de là.

## 5. En relecture : ce que tu vois

Le ticket arrive en *In review*. Sa page s'ouvre maintenant sur le
**Résultat** : ce qui a changé et pourquoi, en mots simples, puis la pull
request, l'état de sa CI et les fichiers touchés. L'état de la CI se tient à
jour sans passer par GitHub, et un check rouge l'emporte sur un check en
cours.

Sous le résultat, le journal que Ponos écrit à la fin de chaque session dit
ce qui a été fait, les choix que tu devrais confirmer, ce qui a été vérifié
et ce qui ne l'a pas été. Le coût et la durée de chaque session y sont aussi.
Sur le ticket de démonstration, c'est une seule session d'environ cinquante
minutes sur `opus`.

Si le résultat est presque bon, tu ne recommences pas. *Request a change*
écrit une consigne sur le ticket et le remet en *Ready* ; la session suivante
lit le résultat tel qu'il est et rend une nouvelle version, la précédente
étant conservée.

## 6. Fusionner est le seul geste

Lis le diff, puis fusionne la pull request, ou passe le ticket en
**Validated** et laisse le runner le faire. Dans les deux cas, le board se
met à jour tout seul : un ticket dont la pull request est fusionnée passe en
*Done* avec un commentaire qui le dit, et rien n'est jamais fusionné dans ton
dos. Un ticket *Validated* peut aussi en déclencher un autre, par exemple un
prompt sur le changement de statut qui crée le ticket de déploiement, comme
sur la page du ticket de démonstration.

## Ce qu'il faut en retenir

Trois habitudes ont fait marcher ce ticket, et aucune n'est propre à Ponos :

1. **Écris les critères de fin.** C'est ce que l'agent vise et ce que la
   relecture vérifie.
2. **Garde le périmètre dans le brief.** « Garde le changement dans le
   module » est une phrase qui économise un tour de relecture.
3. **Garde la fusion pour toi.** L'agent propose, le runner publie, tu
   décides.

## Essaie sur ton propre backlog

Le [guide d'installation](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md)
prend quelques minutes sous Linux ou macOS. Écris ensuite un petit ticket sur
ce modèle, passe-le en *Ready* et regarde tourner la première session. Le
[guide des tickets](https://github.com/hermez-agency/ponos/blob/main/guide/tickets.md)
décrit chaque statut et chaque geste utilisés ici.

*Un produit Hermez.*
