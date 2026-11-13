---
title: "Write the ticket, it comes back done: how Ponos runs Claude Code on your backlog"
description: Ponos turns a ticket moved to Ready into a Claude Code session on a disposable git worktree, and brings it back as a pull request. Here is the loop, step by step.
date: 2026-11-13
tags: [Claude Code, backlog, git worktree, automation]
lang: en
translation: ecris-le-ticket-il-revient-fait
category: Behind the scenes
cover: mascot/og.png
cover_alt: Ponos, the robot, jumping beside its name and the words "Write the ticket. It comes back done."
---

Most of a backlog is work you already know how to describe. A bug with a clear
reproduction, a small feature, a dependency to bump, a paragraph to rewrite.
Describing it takes two minutes; doing it takes an afternoon of context
switching. **Ponos** is built for that gap: you write the ticket, a Claude Code
session does it, and it comes back for you to read.


## The loop is four gestures

1. **Write a ticket** on Ponos's board, the console, and move it to *Ready*.
2. **Ponos does it.** A Claude Code session starts on a disposable `git worktree` of its own, or on a scratch directory when the ticket has no repository.
3. **You read what came back**, and you answer in a word if it asked something, even from your phone.
4. **You move it to *Validated*.** Ponos merges the pull request or publishes the text, and only then calls it *Done*.

Nothing is merged or published until you say yes. That is the whole contract.

## One worktree per ticket

A ticket never touches your working copy. Each one gets a `git worktree` and a
branch of its own, created from `main`, and thrown away once the work is
delivered. Ten tickets can run side by side without stepping on each other, and
your checkout stays exactly as you left it.

```sh
git worktree list
# /home/you/code/app                 9d54118f [main]
# /home/you/.local/state/ponos/...   ab6a441a [ticket/fix-login-redirect]
```

> [!NOTE] Why a worktree and not a clone
> A worktree shares the repository's history with your checkout, so it appears in seconds and costs almost no disk. The session gets a real, isolated working directory without a second copy of the project.

## Not only code

A ticket has a type, and the type decides the road. A **code** ticket comes back
as a pull request. A **writing** ticket comes back as a page written into the
ticket. An **external action** is carried out in a browser or a service's
settings, with every change logged and a stop at the first doubt. A
**publication** is prepared, then published once you validate it.

| Type | What comes back | What it waits for |
| --- | --- | --- |
| Code | A pull request | Your validation, then the merge |
| Writing | A page in the ticket | Your validation |
| External action | A log of every change | Your read of the log |
| Publication | The post, ready | Your validation, then the publish |

## A board that is yours

The board is the console, and its tickets live in a local database, `ponos.db`.
GitHub, Telegram, Slack and OpenRouter plug in when you want them; none of them
is required. A question from a session reaches your phone, and a word in
answer sends it back to work.

> The ticket is the interface. Everything else is Ponos's problem.

## Try it on one ticket

Pick the smallest item of your backlog, the one you have been putting off for a
week. Write it as you would explain it to a colleague, move it to *Ready*, and
read what comes back. The [documentation](https://github.com/hermez-agency/ponos#readme)
covers the installation, which takes a few minutes on Linux or macOS.
