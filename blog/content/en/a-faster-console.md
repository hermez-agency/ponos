---
title: "A faster console: windows that open at once, a table that draws only what you see"
description: Ponos 0.3 makes its console quicker where it counts — the windows, the ticket table, long conversations and the dashboard — with the timings we measured before and after, and the two libraries it now builds on.
date: 2026-11-19
tags: [Ponos, console, performance, react-resource-view, react-data-form]
lang: en
translation: une-console-plus-rapide
category: Product updates
cover: mascot/og.png
cover_alt: Ponos, the robot, jumping beside its name and the words "Write the ticket. It comes back done."
---

Ponos's console is where you watch the backlog move, so a slow click costs
more than a slow page. Version 0.3 goes after the four places where it
was slow: the windows, the ticket table, long conversations and the
dashboard. Here is what changed, and what we measured.

## Windows that open at once

Opening a ticket, the palette or *New ticket* used to hold the page for a
while. Two things were to blame: the animations, and the way the table
styled itself while a window was open.

- The side panel, where the conversation lives, slides in within 200 ms at
  most and closes in 150 ms, instead of 500 and 300 ms. No other exit
  animation of a component lasts longer than 200 ms.
- The table and the windows no longer use CSS selectors that forced the
  browser to restyle the whole page each time a window opened or closed.

On a board of 2,000 tickets, opening or closing a window no longer leaves a
single task longer than 50 ms. Before the change, the palette took 74 ms, a
500-message conversation 79 ms, a ticket window 98 ms, and the palette over
the ticket list 2.9 s to open with four tasks of about a second to close.
The very first opening of *New ticket* still takes 54 to 64 ms, down from
105 ms: it is the first creation of the Markdown editor, paid once.

## A table that draws only what you see

The ticket table now comes from `react-resource-view` 2.1, which draws only
the rows on screen. On a board of 2,000 tickets, the page holds 814 nodes
instead of 57,625. A test refuses the selectors that caused the restyling
in the built stylesheet, so they do not come back quietly.

## The dashboard no longer freezes

On a board of 2,266 tickets, every movement of the table while a ticket ran
blocked the page: 850 to 900 ms of script in the feed's update handler, then
640 to 710 ms of rendering, measured on a slow machine (CPU ×4). Now a
ticket that did not change keeps its row, its card is not drawn again, and
the work is split into pieces. The same movement takes 60 to 100 ms at ×4,
in chunks, and no frame of more than 50 ms was seen over a minute without
slowdown.

## Long conversations stay fast to type in

A conversation of 120 messages made every keystroke wait: the reply field
measured its own height on each key, and every message was drawn again with
each piece of an answer. Now:

- the field grows with the browser's own `field-sizing: content` where it is
  understood (Chrome, Edge): 34 ms per keystroke became 1 ms on that
  conversation;
- messages that are out of view are not laid out, and a message already
  shown is not drawn again;
- a conversation opens on its last 60 messages, and a *Show earlier* button
  adds 60 more without moving your reading position.

A browser test now fails when a keystroke in a 500-message conversation takes
more than 16 ms.

## Lighter first load, and a palette that answers

The console's first page in French went from 508 to 455 KB compressed: the
words of the settings and the first sign-in come with it, and the pages
that need more — a ticket, a project, the ideas — load them when they show.

The Ctrl+K palette filters its own entries instead of letting the library
rank every ticket of the board. On a board of 1,848 tickets, the interaction
delay while typing five letters went from 1,208–1,288 ms to 88–152 ms.

## The two libraries underneath

- **react-resource-view** — the console moved from 0.6 to 2.1. The 2.x line
  brings the virtualised table, and the sticky actions column fixed in 2.0.
- **react-data-form** — on 0.3. Its forms are themed by the console's
  `index.css`, with the expensive selectors rewritten, so that the scrollbar
  width removed from the page is no longer inherited by every element, and
  the page behind a window stops being restyled as a whole.

Nothing changes in how you use the console: the same board, the same
shortcuts, the same windows, only quicker to open and to type in.

## Try it

Update Ponos to 0.3.0 with your usual command, open a board with a few
hundred tickets, and open the palette and a ticket window back to back. The
[guide's console page](https://github.com/hermez-agency/ponos/blob/main/guide/console.md)
describes the views, and the
[installation guide](https://github.com/hermez-agency/ponos/blob/main/guide/installation.md)
covers an update.

*A Hermez product.*
