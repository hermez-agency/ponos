---
title: "Run your backlog from Claude: Ponos's MCP now manages projects, goals and recurrences"
description: Ponos's MCP connector can now create projects, goals and recurring tickets, tie tasks to a goal and launch them after a cost preview — all through the console's own rules, and never deleting anything.
date: 2026-11-16
tags: [MCP, Claude Code, backlog, automation, goals]
lang: en
translation: pilotez-votre-backlog-depuis-claude-mcp-objectifs-recurrences
category: Product updates
cover: mascot/og.png
cover_alt: Ponos, the robot, jumping beside its name and the words "Write the ticket. It comes back done."
---

A week ago, Ponos's MCP connector could read your board and write a draft
ticket. This week it can set the board up. Here is what was merged on `main`
since the last article, grouped by what it changes for you rather than by pull
request.

If you have not met it: **Ponos** turns a ticket moved to *Ready* into a Claude
Code session on a disposable `git worktree`, and brings it back as a pull
request or a written page. The [MCP](https://modelcontextprotocol.io) connector
is the door through which Claude (claude.ai, Claude Desktop or Claude Code) talks
to your board.

## Your assistant can now organise the board

Until now, creating a project, a goal or a recurrence meant opening the console.
Four groups of tools change that, and all of them go through **the console's own
code path**: same names to check, same validations, same errors. A client does
not get a back door.

- **Projects** — `create_project` and `update_project`. Point to a git folder
  already on the machine, give a GitHub `owner/name` for Ponos to clone, or
  create a document project with no repository. A taken name, a missing folder
  or a failed clone is refused and nothing is left half made.
- **Goals** — `create_goal` and `update_goal`: a name, a criterion, a due date,
  a priority from 0 to 100 and the projects it covers. A goal can be turned off;
  it cannot be deleted from here.
- **Tying tasks to a goal** — `set_task_goal` attaches existing tasks to a goal,
  or detaches them. Everything is checked before anything is written, so one
  unknown task refuses the whole batch, and the answer shows each task's goal
  before and after.
- **Recurrences** — `list_schedules`, `create_schedule` and `update_schedule`.

You can now say, in a conversation: *"Create a project for the repo
`acme/billing`, a goal 'Ship invoicing by December', and tie these four tickets
to it."* Claude does it in a few calls, and you read the result on the board.

## Recurrences never switch themselves on

A recurrence is the riskiest thing to hand to an assistant: it creates tickets
by itself, on a clock, and each one can start a paid session. So the rule is
blunt.

> A recurrence written by a client is **always born off**. No tool turns it on,
> launches it or deletes it.

The console marks it **To review** and offers an *Activate* button. You read the
mission, the cadence and the type, and you press the button yourself. That is the
same posture as the rest of the connector: a ticket a client creates is a draft,
and nothing deletes data.

## Recurrences can serve a goal

Recurrences got a field of their own this week: **Goal**. A schedule that serves
a goal ties every ticket it makes to it, whether the ticket is born at the
appointed hour or from *Run now*. The goal's progress bar — *n of m tickets
done* — then counts the recurring work too, instead of leaving it on the side.

If you run a weekly dependency bump or a weekly report, this is the missing
link: the goal "Keep the product healthy" now reflects the chores that actually
keep it healthy. A goal that is over, or deleted, does not stop the schedule; its
tickets are simply born without one.

## Launching, with a price tag

`launch_task` lets the assistant move tickets to *Ready*, which starts paid
sessions. It works in two calls on purpose. Without `confirm`, nothing changes
and you get a **preview**: the tasks kept, with project, model and estimated cost,
and the ones refused, with the reason. Only after your explicit yes does the
second call, with `confirm: true`, launch them. Every launch is written in the
ticket's history under the client's name. If you would rather keep that gesture
for yourself, switch off *The assistant may launch tickets* in the settings.

## A ticket page that reads better

Two changes in the console you will see every day:

- The ticket page splits **Mission** and **Result** into two tabs. *Mission* is
  always there; *Result* only appears once the work is done, so the page of a
  running ticket no longer shows an empty slot.
- The **On** prompt, which Ponos runs at each change of status, was hidden under
  the journal. It now has its own field at creation and its own section in the
  Mission tab, and it can be written from the MCP as well.

## Cleaner commits, and a disk that stays in bounds

Two quieter changes, both about trust:

- **Sessions no longer sign commits and pull requests as Claude.** No
  `Co-Authored-By` line, no "generated with" footer — unless you turn the
  `claude.attribution` setting on. Your history reads as yours.
- **Rotating logs.** The `logs/` folder never exceeds `runner.log_max_mb`
  (4 GB by default, adjustable in the settings). Beyond that, the oldest session
  logs go first. A runner that lives on your machine all year should not slowly
  eat it.

Ponos also stopped committing agent-tool files to your repositories: instructions
live in `AGENTS.md`, and a worktree that only has it gets a one-line,
never-committed `CLAUDE.md` pointing there.

## Try it

Connect Ponos to Claude once — *Settings → Connectors → Add custom connector*
with `https://<your console>/mcp`, then **Connect** — and ask *"what is waiting
for me?"*. Then ask for a goal and a recurrence, and open the console to review
what Claude drafted. Nothing it creates is switched on without you.

The [installation guide](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md)
takes a few minutes on Linux or macOS, and the
[MCP section of the console guide](https://github.com/hermez-agency/ponos/blob/main/guide/console.md#connect-ponos-to-claude)
lists every tool and what it is allowed to do.

*A Hermez product.*
