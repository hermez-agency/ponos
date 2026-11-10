# The console

[The guide](README.md) · [Ponos](../README.md)

The web console, and Ponos as a connector in Claude.

## The web console

A database is where tickets are kept; it is no place to *steer* from. So there is a
window on it, served from your own machine — and it is running
already: the installer starts it and prints the address, token included. On an installation
nobody has set up yet there is no token to paste either — the address alone opens
[the first connection](#the-first-connection), which is where the rest of this page's
configuration gets filled in.

```sh
ponos service run --print-token   # the token, if you lost the URL
```

Open `http://127.0.0.1:8787` and you get one page, four things:

```
┌───────────────┬──────────────────────────────┬─────────────────────────────┐
│ Ponos         │        ● live  v0.9.2  ⟳  ☀  │  you                        │
│               │ + New ticket   board · table │  Where is the SQLite ticket │
│ ▸ Dashboard 4 │  Ready     1   In progress 1 │                             │
│   Projects    │  ┌──────────┐  ┌──────────┐  │  workspace                  │
│   Schedules   │  │ Retirer  │  │ Migrer   │  │  Six minutes in, on Trader  │
│   Context     │  │ le       │  │ vers     │  │  IA. It has rewritten       │
│   Settings    │  │ bandeau  │  │ SQLite   │  │  src/billing.py and is on   │
│               │  │ High     │  │ pytest   │  │  pytest. Nothing committed. │
│               │  └──────────┘  └──────────┘  │                             │
│               │                              │  > status                   │
│               │                 ───▶      (●)│  1/2 places · 3 waiting     │
└───────────────┴──────────────────────────────┴─────────────────────────────┘
     the menu           the board, live            the drawer the bubble opens
```

**The menu** down the left is where the pages live: a name each, and a count beside it
where something is waiting there — how many tickets are on the board. On a phone the menu runs
along the bottom edge instead: the board, the projects, the ideas, the conversations — *Chat*
there, where the whole word is cut — and **More**, which
opens the settings from the bottom of the screen — the bar
fits a 360px screen and never scrolls sideways. No bubble floats over it: on a phone the
console opens from **More**, so nothing a page draws is ever under a button. The frame is react-resource-view's admin layout (see
[The console's own code](../CONTRIBUTING.md#the-consoles-own-code)), and the end of its bar holds the things
about the console itself: whether the event stream is up — a stream the server refuses
because the session expired sends the page back to the sign-in rather than saying
*reconnecting…* forever — the version this one runs — in amber, with what to type, on the
day a newer one is waiting — when the board was last read whole, a green dot that
turns amber when something is out of step (the tooltip says what), and the two buttons
that **resynchronise** — the whole board read again, the refused moves sent again; the icon
turns while it runs, and *Board read again* says when it is done — and change the light. On a phone, where the bar has room for none of those words, the stream,
the last read and the version are one pill — a dot and *live* — that a tap opens on all
three. Every page has an address — `/?view=console/tickets/list`,
`/?view=console/tickets/read/<id>` — so a reload, a bookmark or a link pasted into a chat
lands where you were. A typed name leads to its page — `/projets` or `/projects`,
`/objectifs`, `/reglages`, `/conversations` and the like — and an address the console does not have
says *Page not found* and lists its pages. The page of *running* sessions the console used to have is gone, and its old
address leads to the board: a ticket's session is followed on its ticket.

**Conversations** is the entry for your exchanges with the workspace, the ones the bubble
opens — a *session*, everywhere else in the console, is Claude at work on a ticket, and only
that. Each is kept in `ponos.db`, so they survive a restart: the page lists them
from the latest to the oldest, with a title made of the first message (renamable, as is the
project it is about), the date of the last message and the model it ran on. A row reopens the
conversation with its whole transcript and carries on where it stopped — it is the same Claude
Code session, resumed. The search looks in the titles and, failing that, in what was said;
*New conversation* starts another; deleting asks for a box to be ticked, as deleting a project does,
and takes the transcript and the files sent in it. The model is chosen from the conversation
itself, in the bar over it, and kept per conversation: the Claude models (`opus`, `sonnet`, `haiku`,
`fable`) and, once `OPENROUTER_API_KEY` is set, any model OpenRouter lists — searched by name, the
ones you used last first. A conversation on an OpenRouter model talks to OpenRouter whatever
`claude.provider` says; without a key the picker offers Claude's models and leads to the
setting. `web.chat_model` is the model a new conversation starts on.

**Several conversations answer at once.** Each conversation has its own run — the turn in
flight, the messages waiting behind it, its Stop, its stream — so you can send a message in
one, switch to another, send one there, and come back: the first went on in the background,
and the page catches up with it as it reopens. Which conversation is open is the *tab's*
business, not the server's: two tabs, or a phone and a computer, follow two different ones.
Starting, opening, renaming or deleting a conversation is never refused because another is
answering; deleting one whose turn is running stops it first. The history menu and the
**Conversations** page mark the ones answering (a pulsing dot), the ones waiting for a place
(a hollow dot) and the ones that answered while nobody was reading (a plain dot); the
history button carries a dot when another conversation is answering or unread. Each turn is
a Claude session that spends the same subscription, so at most three (`Web.chat_max_turns`, a constant of the code)
run at once: past it, a message waits in its own conversation — *Waiting for a free
place* — and starts when a turn ends. A `>` command is not a turn and runs whatever the
conversations are doing, one command at a time. The API names the conversation:
`GET /api/chat/<id>`, `POST /api/chat/<id>` (send), `/api/chat/<id>/agui` (the AG-UI door),
`/stop`, `/read`, `/model`, `/queue/…`, `/attachments`; `POST /api/chat/new` makes a blank one
(on the model of `{"like": "<id>"}`), and `GET /api/chat` answers the latest, where a tab
with none starts. The event stream says which conversation each `chat` and `agui` event is
about.

**The dashboard** opens on the period's [statistics](#statistics-on-the-dashboard), then
the board. **On a phone** it opens on **To handle** instead: the blocked tickets and the
ones in review, one card each — a blocked one first, then the pull requests to decide, then
the stops Ponos is already retrying; the one waiting longest first in each. A card says
why the ticket waits and carries its gesture: *Unblock* opens its discussion on the question
and its quick replies, *Decide* the numbered choices of its pull request — a tap there, a
tap on the answer. The first four are drawn, *Show the N others* the rest, and *Unblock (N)*
and *Decide (N)* in its heading go through a whole column. Under it the statistics are
folded until you open them (the choice is kept, as on a computer), and the board shows one
column at a time under a row of tabs with their counts — *Blocked 3 · In review 2…* —
opening on *Blocked*, then *In review*, or on the tab you left. **The board** is the board of `ponos.db`, read from it and written back to it, drawn as
the columns the board has — *Ready*, *In progress*, *In review*, *Validated* where the
board offers it, *Blocked*, *Done* — under the board's own names. Nothing here
is a second database: **drag a card into a column and the ticket moves**, and the ticket
you write behind *New ticket* is a ticket like the others, with its brief in Markdown
— and its *Priority*, *Type* and *Model* (an empty type is deduced by the runner, as for a
ticket written from the MCP). *Ready to
run* is ticked by default, and the form says what that means: a session, as soon as a
place is free. **Ctrl+Enter** (⌘+Enter) creates the ticket from any of its fields. What the console adds is the part a database cannot do — the running session's
steps, live, read straight from the session log on disk rather than from the `Progress`
column. A card in progress has a pulsing dot, how many steps its session has taken, and
what it is on in one line — what the agent last said, or else the last tool it ran. Over
the columns, one strip carries the runner's figures: the sessions writing, the daemon's
places (taken over all, and how many tickets wait — clicked, which ticket holds each place,
per project, and the queue with why each ticket waits: every place taken, its project at
its limit, a ticket it comes after, a date, the credit), the tickets handled and what they
cost. A ready card carries **Run now**: the daemon gives it a free place at once, or says
none is free and offers to run it past the limit, once. A card in review carries a
**validate** button, where the board has that column: confirm it and the daemon merges its
pull request at once, or publishes what it holds at the next free place; *run again* asks
the same way, since it starts a session that is paid for. A move is queued by
the console rather than made while the browser waits: the card lands in its new column
saying it is on its way, the console reads the ticket first — and **does not overwrite a
status somebody changed since the card showed it** (a run, the MCP, a channel), saying so
on the card instead — writes it, reads it back to confirm, and tries again with a growing
wait when the board is busy. A move refused for good says so on the card, and stays said until *resynchronise* or another move. The queue is
kept on disk (`~/.local/state/ponos/web/outbox.json`), so a console restarted
mid-way still sends it. A gesture that sends a card off the screen —
*hold*, into your *Blocked* column — says where it went. A ticket with no status, or one
your board has not named, is not hidden: it sits in the first column, *Draft* (*Brouillon*
in French), with the drafts. A long column draws its first fifty cards — *Done* and
*Cancelled* their thirty latest — and *Show more* under it the next ones; a card you drop
there stays in sight, wherever the queue ranks it. Seven columns do not fit a laptop, so the board scrolls sideways, and each
edge with more beyond it shows a fade and an arrow. The *table* tab shows the same tickets
as rows, one column per property.

**Several cards at once.** An audit writes thirty drafts in one go, and launching them one
card at a time was thirty clicks and thirty confirmations. Hover a card and tick the box in
its corner — on a phone, press and hold the card — and the board is picking: a click (a tap)
on any card picks it instead of opening it, **Shift**+click picks every card between it and
the last one picked, and the box beside a column's name picks every card the column draws
(those the search kept, as far as *Show more* went). A bar along the bottom acts on them all:
**Make ready** — drafts, failed runs, and tickets set aside by hand; a ticket blocked on a
question waits for its answer —, **Set aside** for the *Ready* ones, **Priority** (a score
from 0 to 100, where the board has the column), **Goal** (or none), and **Give up**, into
*Cancelled*, for anything the runner does not have in hand. Each gesture takes only the
cards it applies to and says how many when that is not all of them. Launching asks once, for
the lot: how many sessions start, what they are likely to cost — the sum of the
[estimates](credits.md#before-a-ticket-starts-the-estimate) there are, those without one counted apart — and their titles. Giving
up asks once too; the other three are done at once, as on a card. Ten drafts are launched in
four gestures: a box, a Shift+click, *Make ready*, Enter. Escape or the **×** lets the
selection go. The priority is written by `POST /api/tickets/<id>/priority` (`{"priority": 80}`).

**A search bar sits over the columns**, the same on a project's *Tickets* tab. Its field
looks for every word typed, in any order, case and accents set aside, in the title, the
runner's line on the card (the RESULT a run ended with), the pull request's address — so
`#201` finds it — the project and the runner; a short id finds its ticket from four
characters, and a pasted branch, worktree or ticket address finds the one ticket it names.
Beside it, filters that combine with the words and with each other: *Type*, *Sub-type*, *Status*,
*Priority*, *Model*, *Project* (not on a project's page), *Period* (created or changed
today, in the last 7 or 30 days) and *Other* — with a pull request, waiting for credits,
a move not yet synchronised, a cost above $1, $5 or $20. Each list offers only what the
board's tickets carry, with how many carry it. A search hides cards, not columns: each
column says how many it kept, `3 / 12`, the words found are marked on the cards, and a
search that keeps nothing says so with a button to clear it. It is all in the address
(`&q=…&type=code,writing&status=ready`), so a filtered board is a link to send and survives
a reload and the switch to the table. **/** goes to the field, **Escape** empties it. On a
narrow screen the filters fold behind one *Filters* button. It searches what the board
already holds, so it is instant; the brief, which the board does not carry, is not searched.

**A card is a way in.** Click one — or a ticket's title in the table — and the ticket opens
in a window over the board, the whole screen on a phone; its header has its short id, its
title, a button to its full page and a cross (Escape closes it too), and the board is
where you left it underneath. The full page has an address of its own, the one a shared
link, the palette and a notification open. Either way it is the brief you wrote, the
report a run appended, the notes in between — the page under the card, as the runner
reads it — with its links out (the pull request, the session) and the gestures it
offers where it stands. Under the column it stands in, three tabs: **Brief** — the facts
(project, type, priority, model, cost, pull request) and the page you wrote —,
**Discussion** and **Live**. A ticket in progress opens on *Live*, one waiting on you on
*Discussion*, any other on *Brief*; the tab you pick goes into the address (`&tab=live`),
so a reload or a shared link comes back to it. *Live* wears a green dot while a session
runs, *Discussion* a question mark while a question waits for you. *Live* is the session's
journal in its broad lines, growing as it is written and following its end until you
scroll up to read something: what the agent says is one line each, drawn as prose, and the
tool calls that followed it — up to the next thing it said — are folded under it, the
toggle saying how many steps, how long, and how many failed, marked in red. The steps
before it said anything are a group of their own, *Getting ready*. The line being written
says what the agent is on, in a few words, without unfolding anything; *Unfold
everything* opens them all at once, and a line you opened stays open as new steps arrive.
Unfolded, each tool call is one line — the tool and the start of its command, the
worktree's path written `./` — that a click unfolds in turn. The steps come from the local run
journal (`ponos.db`, below), not from the page: the tab opens on the end of the newest run,
*Earlier steps* reads further back two hundred at a time, and while the run goes on each
step the stream announces is read from the journal as it lands. Every run the ticket has
had is kept there — a select over the steps picks an earlier one, by its date, how it
ended and what it cost — and the line above them says how it ended, with the pull request
or the reason; a finished run reads in the same broad lines. A ticket whose runs all predate the journal is read back from its last log,
as before. The **discussion** tab is the ticket's own terminal, counted on the
tab itself: everything said on it, oldest first — the runner's reports, your answers, the
answers you gave from Telegram — and the console's own message bar to say the next thing
(Enter sends, the microphone dictates; no files, since a comment carries text). A ticket
**waiting on you** — in *Blocked*, or with a question a run asked and nobody has answered
yet — opens on that tab, and its card on the board says *waiting for you*, or the cause it
stopped on when the runner knows it (*Question for you*, *Credentials missing*…). What you type is a
*comment on the ticket*, written into the thread the runner last spoke in, which is the
gesture the runner already knows: an answer under the question a run asked puts the ticket
back in the queue, and one that names it — `@claude`, `@ponos` or `@runner` —
asks it for words instead. Nothing is kept on the side; the same sentence sent from the MCP
does the same thing.

**The bell.** The icon in the header counts the tickets waiting for you — not the notifications —
and opens a dropdown over the board: one line per ticket, those still waiting first — every one the badge counts, however old — then
the latest read, saying what it rang for
last with an icon, how many times it rang so (« 3 questions »), the ticket's title, its project and
how long ago. A click opens the ticket's card and marks everything that ticket rang for read; *Mark all as
read* empties the badge; Tab and Enter reach everything, Escape closes it, and on a phone it spans
the width of the screen. It rings for a session that stopped on a question, a pull request ready to
read, a pull request whose checks fail (`merge.checks-failed`), a failed session and any other
blocked ticket — and for nothing routine. The run writes them into `ponos.db` (`notifications`;
one unread per ticket and kind), the console reads them off the same stream as the board, and a
notification read more than thirty days ago is purged.

**The bell on your phone.** *Settings → Communication → Notifications on this device* pushes the
same moments to a phone (or any browser), the console closed and the phone asleep — Web Push, with
no third party to sign up to: the console signs what it sends with a key of its own (VAPID, drawn
the first time a browser asks for it, kept in `~/.local/state/ponos/web/vapid.pem`) and encrypts
it for the browser that subscribed, so the push service (Google's, Apple's, Mozilla's) carries it
without reading it. A push leaves when the bell rings anew — once per ticket and kind until it is
read, and a ticket that asks again replaces its notification rather than stacking another one —
and touching it opens the ticket on the tab its decision is taken in: the discussion of a blocked
ticket, *Decide* for one in review. *Send a test* checks that it arrives; the card lists the
devices that receive it, and a phone lost or replaced is removed there (one its push service no
longer knows is removed by itself). Three conditions the browser sets, which the card says when
one is missing: the console over HTTPS — `ponos tailscale` [gives it one](#from-your-phone-and-from-claude-ponos-tailscale),
a reverse proxy too —, notifications allowed for the site, and on an iPhone the console added to
the home screen (*Share → Add to Home Screen*) and opened from there: Safari pushes to installed
apps only. There are no quiet hours of Ponos's own — the phone's *Do Not Disturb* already has them.

**Unblock and Decide.** A *Blocked* card carries one button, **Unblock** — no *answer* or
*make ready* beside it — and a card *In review* a **Decide** one. Unblock opens the ticket's
window on its *Discussion*, marked with a question mark and scrolled to the end; Decide on a
tab of that name, beside *Brief*, *Discussion* and *Live*, there only while the ticket is in
review. The same button on the ticket itself switches to it, and on its page the tab is in the
address (`&tab=discussion`, `&tab=decide` — an old `&tab=unblock` link opens the discussion).
In the discussion, the report the session stopped on is drawn once, as Ponos speaking: what is
done, why it stops, and the question in bold. Under it, quick replies, each a click that
answers and runs the ticket again: *Yes* and *No* for a yes-no question, one per option —
in full, never cut — for a choice, *Yes, close it* when the session proposes to close the
ticket (a duplicate, nothing to do), which files it as *Done* with a comment, and always *Run
it again as it is*. One field under them takes an answer or an instruction alike (Enter or
Ctrl+Enter sends), with the model to run it on next beside it on a board with a *Model*
column; *Run it again as it is*, *Abandon* — confirmed first — and *See the session* are behind
the ⋯ of the discussion. Once something is sent, Ponos is shown at work under it — the robot
of the *Live* tab, *Ponos is working…* — until it says something back, or the session fails,
which is said in its place; the quick replies wait meanwhile. The run's lines in passing —
*Model chosen automatically*, a session that committed nothing — are one small grey line
across the discussion, not a bubble nor a red badge. Decide shows the session's sentence,
the pull request, its checks as GitHub says them now — each job by name, green, red, skipped
or still running, a link to its page — the files the pull request touches, each with its lines
added and removed (the first twelve, then *and N more* towards GitHub; the diff itself stays
GitHub's), and the points the session said it could not check: enough to merge a green pull
request from a phone without opening GitHub. Then *validate*, *send back with an instruction* — ready-made for red checks,
missing tests, screenshots, a rebase, or any of those points — or *reject*. Each choice writes
one comment — *Answered from the console. Decision: run it again on opus.* and the words you
typed — which the next session reads as yours, then moves the ticket: to *Ready* to work
again, *Validated* to merge, *Done* — or *Cancelled*, on a board that has that column — to
file it away. *Split into sub-tickets* writes them as drafts, on the project and the
[goal](#goals) of the ticket they come from, so they still count toward it. The MCP server's `list_solutions` still lists every choice a blocked ticket
offers — *it's done, run it again*, *split into sub-tickets* and the rest — for an assistant
to pick from.

**One after another.** From two blocked cards on, the *Blocked* column's heading offers
**Unblock (N)**, and *In review*'s **Decide (N)**; Ctrl+K has them too (*Unblock the tickets*,
*Decide on the tickets in review*), and the address keeps them — `/?series=blocked`,
`/?series=review` — to come back to or to share. They open one window, the whole screen, that
goes through the column a ticket at a time: at the top *2 / 5*, a progress bar and the list of
its tickets — short title, project, cause — any of which a click jumps to; in the middle the
ticket's title, project and cause, then the same choices as its *Decide* tab — on a blocked
ticket, the question as its discussion says it and every way out the session's report offers,
its own options numbered. Once one is sent the next comes, with *Ticket unblocked — Undo* over
it, which puts the last one back in its column. *Previous*, *Skip* and *Open the ticket* (in a
new tab) are under it, and the keys: → or J skips, ← or K goes back, 1 to 9 picks the session's
option, Escape closes. The questions come first, then the missing accesses, then the rest, and
last the stops Ponos tries again by itself or that wait for the base; inside each, the highest
priority, then the oldest. A ticket that moves elsewhere meanwhile — its session, a channel,
another tab — leaves the series as it happens. At the end, what was done — *4 tickets
unblocked, 1 ticket skipped* — and *Review the skipped tickets*.

**The drafts, too.** The *Draft* column's heading offers **Sort (N)** (Ctrl+K: *Sort the drafts*, address `/?series=draft`): the same window, with each draft's title, project and page read as Markdown, and two choices — **Ready** (the ticket joins the queue) or **Abandon** — plus *Skip*. Keys: Enter or R makes it ready, A abandons it, → or J skips, ← or K goes back; the last choice can be undone. A draft is not edited there: *Open the ticket* leads to its page.

All of it is read off the report the runner already writes. A session that stops names the
kind of thing it stopped on (a `CATEGORY:` line beside `WHY:` and `QUESTION:`), which the
report writes in front of why — `Missing access: I have no SSH key for the server`; a session
that ends ok lists what to check (`CAVEAT:` lines), written `To check: …` under the pull
request. A report from before those lines, or one the runner wrote itself — a conflict, a red
CI, a spending limit — is read off its words, and offers the defaults of the kind it reads as.
The same panel is in the MCP connector, as `list_solutions` and `apply_solution`.

The comment is written by the console in the runner's name — and it opens the same way an
answer relayed from Telegram does, so the next run reads it as yours rather than as its own
voice.

**The console** is behind the bubble in the bottom corner, on every page, a ticket's
included — on a phone, behind **More** instead — one press opens it as a drawer over the page, another closes it, and no page is given up for it. It is one message bar and
two gestures, and they are not made to look alike.

Two keys reach it without the mouse. **Ctrl+J** (⌘J on a Mac) opens and closes the
drawer, the cursor already in its message bar — type straight away — and gives the focus
back to wherever it was when it closes; Escape closes it too. **Ctrl+K** (⌘K) opens a
palette: the pages (Conversations among them), the projects, the tickets on the board, and a
few actions — every creation (a new ticket, project, idea, goal, schedule or conversation), the
console, a resynchronisation —, found by typing a few letters and opened with Enter. An
entry is found when every word typed is in its name, in any order; tickets are found by
their title, their project or the start of their short id, twenty at most, the open ones
before the finished ones — more letters narrow the list. On a
project's page, the new ticket is *New ticket for* that project, its form opened with the
project already chosen. Both answer from inside a field as well; the magnifying glass in
the bar opens the same palette, and its tooltip and the bubble's say the keys. A third,
**/**, goes to the search over the board, and a fourth, **N**, opens *New ticket* — for
the project whose page is open, if one is — both only from outside a field and with no
window open; the palette prints N beside its entry. They are listed in one place,
`frontend/src/lib/hotkeys.ts`, which is where a fifth one goes.

- A line starting with `>` is a **`ponos` subcommand** — `>status`, `>list`,
  `>doctor`, `>logs 1a2b3c4d`. The CLI is already the considered surface of this
  tool, so the console does not invent a second one; the command runs as a subprocess with
  no shell, and its output streams into the page. There is no shell in the browser, on
  purpose: it would add every risk and no capability the chat does not already have.
  What it offers is a list written down — `doctor`, `history`, `list`, `logs`, `notify`,
  `projects`, `schedules`, `status`, `sync` — and not the whole parser: `run` starts
  sessions that outlive a typed command, `update` replaces the code the console runs on,
  and `clean` deletes worktrees a session may be standing in, so those three (with
  `service`, `config` and `open`) are for a terminal. A command gets
  three minutes, and at the end of them its whole process group is stopped, not only the
  process the console started.
- Anything else is a **message to your workspace**. One long Claude Code session, started
  in `workspace_root`, carried on from turn to turn — with your repositories under its
  feet and `ponos` on its PATH. *"Create a ticket for the SQLite migration on
  Trader IA and make it ready"* is a thing it does, not a thing it explains how to do.

That conversation is a real session, like every ticket's: `claude --resume <id>` in a
terminal opens the very same one, and it survives the browser, the server and the machine.
The line under the drawer's title says how many turns it has had and copies that command
when clicked. *New conversation* — the pen at the top of the drawer — starts a fresh one
beside it: the old one stays resumable by its identifier, and goes on answering if it was.

**While it answers**, the conversation shows Ponos thinking — the flame swaying, the eyes
searching — and one line about what the session is on, said in words rather than in tool
names (*I read the project's code*, *I check that everything works*), with the time spent.
Under `prefers-reduced-motion` Ponos holds still and the line says it all. The steps
appear under it one by one, as a vertical timeline of cards, and stay after the turn: each
card is titled in plain language, in the console's language — never a shell command or a
tool's name, whatever it is not sure of being *I work on the project* — with a mark for
going on, done or failed. Cards start closed; opening one shows the exact detail (the
command as typed, what the tool answered when it failed), and *Expand all* / *Collapse
all* does it for the lot. A line above the cards says how many steps, how long and what it
cost, and a red dot counts the ones that failed, without opening anything.

**Stop.** While a turn runs, the arrow of the bar becomes a square: a click — or Escape,
from an empty field — ends the session's whole process group, the command it was running
included, so nothing it started carries on. The conversation says *stopped by you*, keeps
what had been said and the folded steps, and puts you back in the field: the next message
resumes the same session, which remembers what it was doing. A second click, or a turn
that ends at the very moment you press, changes nothing — the answer that had arrived is
kept. (A first turn stopped before Claude Code wrote anything leaves nothing to resume; the
next message starts the session afresh.)

**The message bar** is one rounded block with everything it can carry inside it: the files
above the words, a **+** on its lower left, and on its right the microphone and a round
arrow that sends — greyed while there is nothing to send, turning into *Stop* while the
workspace answers. The field grows with what you write, up to about eight lines. Typing
`>` switches it to the command gesture: the text goes monospace, a small *command* label
appears, and a menu above the bar offers the verbs above as you type (arrows, then Tab or
Enter). Drawn full screen, the bar keeps a reading width of 48rem, centred.

A message can carry **photos** (png, jpg, webp, gif), **videos** (mp4, webm, mov) and
**documents** (pdf, txt, md, csv, json, docx, xlsx), added three ways: the **+**, a drop
anywhere on the drawer — a zone lights up while a file is over it — or a paste, which is
how a screenshot arrives (it is named `screenshot-<time>.png`). Each file is uploaded as
soon as it is added, shows as a thumbnail (the first frame, for a video) or as a chip with
its name and size, and leaves by its cross. A file over `web.attachment_max_mb` (25 MB by
default) or of another kind is refused with a sentence saying which and why. In the
conversation, what you sent sits above your words; a picture or a clip opens in full with
a click, a document in a tab.

Claude Code takes no file in a request — it reads them from the disk — so the files are
kept under the runner's state (`~/.local/state/ponos/web/attachments/`, never in a
repository), and the message the session receives names each by its absolute path with a
word on how to read it: an image or a PDF with its Read tool, a spreadsheet or a Word file
with what the machine has. A **video** cannot be watched as such: when `ffmpeg` is
installed, eight frames are taken along it and those are what the session looks at; when
it is not, the session is told it cannot see the clip, and says so rather than guess.
*New conversation* deletes the conversation's files; whatever a conversation nobody closed
left behind goes after `web.attachment_days` (7). `ponos doctor` says whether
`ffmpeg` is there.

**Dictation.** The microphone records (Alt+Shift+M from the keyboard, Escape to throw the
recording away) with a clock and a small wave, then *Stop* or *Cancel*. The recording goes
to the server, which has it transcribed by OpenRouter (`openrouter.transcription_model`,
`openai/whisper-1` by default) in `runner.language` — or, when that is empty, in the
language the console is shown in — and the text lands in the bar, to be read over and
corrected before you send it. `web.send_after_transcription = true` sends it as soon as it
is back. Without an OpenRouter key, or with a microphone the browser blocks, the button is
greyed out and its tooltip says which.

**Voice.** The console can read its answers aloud and hold a spoken conversation. The
voice is made on this machine by [Piper](https://github.com/rhasspy/piper): no service hears
what Ponos says.

- *Listen*, under each answer, reads that answer; pressed again, it stops.
- *Voice mode*, the waveform button in the bar, is the hands-free loop: it listens, a
  silence of a second and a half after you spoke ends the sentence, which is transcribed
  (as in Dictation above) and sent at once; the answer is read sentence by sentence while it
  is still being written, then it listens again. The strip over the bar says *Listening…*,
  *Thinking…* or *Speaking…* with the same wave as the microphone's. Talk over the voice,
  or press *Interrupt*, and it stops; *Leave* ends the mode. It needs the microphone, the
  OpenRouter key of Dictation and Piper — without one of them the button is greyed out and
  its tooltip says which. On a phone the first tap is what lets the browser play sound at
  all (iOS and Safari refuse it before a gesture), so the mode starts from the button and
  never by itself.
- What is read is not what is written. Code blocks, tables and links are not read out: a
  block becomes *"Je t'ai mis le code à l'écran."* (*"I put the code on screen."*), a link
  becomes *"un lien"*, the markdown is dropped. Past about 700 characters the rest of a
  long answer is left to the screen with *"Je t'ai mis le détail à l'écran."* The full text
  stays displayed. Use a headset in voice mode: through loudspeakers the voice reaches the
  microphone and can end up interrupting itself.

*Setting it up.* Piper is optional, the `voice` extra: `ponos extras add voice` installs it
in the environment of the version in use and declares it (`[install] extras`), so that every
update gives the next version's environment Piper too — see
[Optional extras](installation.md#optional-extras-voice-browser). When it is missing, the
greyed-out voice button offers *Install the voice* (an admin's button) which does the same.
In Docker, add it to your own image. `[speech]` in
`config.toml` (Settings → Models → Voice) switches it on or off (`enabled`), names the voice
of each language (`voice_fr`, `fr_FR-siwis-medium` by default, `fr_FR-upmc-medium` is
another; `voice_en`, `en_US-lessac-medium`) and the pace (`speed`, 100 is normal). The
language is `runner.language`, or the one the console is shown in. Voices are not shipped:
the first sentence in a language downloads its model — a `.onnx` and its `.onnx.json`, about
**60 MB** for a medium voice — from the `rhasspy/piper-voices` repository into
`~/.cache/ponos/voices` (`$XDG_CACHE_HOME/ponos/voices`); delete the folder to get the
space back. The model is loaded when the mode opens, so the first sound follows the first
sentence of the answer by about a tenth of a second on an ordinary machine (loading the
model takes two seconds). `ponos doctor` says whether Piper is installed and which voices are
downloaded. The API behind it is `POST /api/chat/speak` (`{"text", "lang"}` → `audio/wav`) and
`POST /api/chat/speak/plan` (the sentences worth saying of a reply), both behind the console's
sign-in like every other route.

An address written anywhere the console shows text — an answer, the output of a command, a
step of a session, a comment on a ticket — is a link you can click. A pull request the
runner just opened is one click away, not a URL to read out loud into another tab.

**Projects** is every project of the [projects database](board.md#the-projects-database) of
your board, and where its repository turned out to be on this disk. One name on a card
that says how many tickets point at it, and what it declares — so "no repository could be found" has somewhere to be answered. A search field
finds a project by a part of its name (or its type) and a *Type* menu keeps the code projects or
the documents; both are kept in the address, so a shared link or a reload opens the same list.

It is drawn in **three layouts**, and the tab you are on is in the address. *Columns*, the one
it opens on, puts the list on the left, one compact line per project (icon, name, type, tickets,
last activity), and on the right the project picked in the list (the global context is no longer here: it has [its own page](#the-context-page)): its
page, the very one its address opens — the same header (*+ Ticket*, *Edit*, the “…” menu), the
same figures and the same *Tickets*, *Ideas*, *Schedules*, *Brief* and *Settings* tabs — without the way back
to a list that is right there, and with *Open the project's page ↗* to see it alone, on the tab
the panel is on (`&tab=ideas`). The tab picked is kept from one project to the next, and a
project is read once for the panel and the page alone. On a screen too narrow for two columns,
a phone, a project picked opens its page. *Cards* is for a
workspace you half remember: a project is recognised by its name and its shape rather than
read. *Table* is for comparing them — which of these eleven has no repository, which has
no path on this machine — because that is a question a grid of cards will not answer.

**And a project is a page you can change.** Open one and it says what it declares and, under
that, its *brief* — the audience, the voice, the conventions, the things never to do, which
every ticket of that project is told before it is told the ticket. *Edit* opens the same
four fields the page holds: the name, the repository, the path, and the brief itself. What
is written goes to the column your page already carries — `Repository`, `github` or `repo`,
whichever you named it — rather than to a second one beside it.

**What else a project's page gathers.** Its *Schedules* tab (`&tab=schedules`) is the list of
the schedules whose tickets are for it, in a table or a calendar, with *New schedule* already
set on the project. Under the figures of its *Tickets* tab, a *Goals* box lists the active goals
that name it, each with *n of m tickets done* and its bar, and *See every goal of the project*
opens the Goals page kept to it.

**A project can be deleted** — from its card or row (the “…” menu) and from its page, next to
*Edit*. A dialog names it, counts the tickets that point at it and asks for its name before
the button turns on; the server asks for the name as well. A project that is only hidden would
still be synchronised, and the runner would still take its ready tickets, so deleting is done
where the runner looks: the project's page is put in the board's trash (flagged in `ponos.db`,
never erased), and the project leaves the console at once, without waiting for a synchronisation. Its tickets stay on
the board by default, but the ready and in-progress ones are put in *Blocked* with a comment
saying why; a checkbox in the dialog trashes them too. The GitHub repository, the folder on
this machine and the branches are never touched, only the throwaway worktrees under the state
directory are cleaned (one with uncommitted changes is kept). The project's ideas are deleted;
**what it spent stays in the history**, since the global statistics are a sum over it. A project with a session running on one of its
tickets cannot be deleted: stop the session or wait for it to end. A ticket that still points
at a trashed project is blocked by the runner, never worked on.

**Schedules** is [what comes back on its own](tickets.md#what-comes-back-on-its-own), read the way
`ponos schedules` reads it: what repeats, at what rhythm, when the next ticket is
due and when the last one was made. Like the board and the projects, it is drawn in the
layouts the view package brings rather than in a design of its own — and the pair is the
point. *Table* is for comparing them, and for the one gesture this whole feature is built
around: `Active` is the only cell you can type in, so **unticking a row in the list stops
it**, without deleting anything and without opening a form. *Calendar* is for the only
question a schedule really answers — when the next one lands: the occurrences are laid out
by day, week or month, and clicking one opens what it will make.
The list is answered from the rows the console already holds — read once when `ponos service run`
starts — so it opens at once: a schedule written elsewhere — from the CLI, from another tab — shows a
moment later, once the read the console makes behind the answer finds it, and the page reads its
list again then.

*Split*, the layout the page opens on, is the projects' two columns: the schedules on the
left — rule, switch, next run, project, a badge when something is wrong — and on the right
the one picked, in the address (`&schedule=<id>`) so a link opens on it: its header and its
actions (run now, edit, delete, the switch that pauses it), what it made — tickets, their
standing, their total and average cost, their average duration, how many of those that
finished are done, a chart by week — and three tabs under them: *Tickets*, every ticket it
made, newest first, each opening in its window; *Runs*, every time it came due, with the ticket it made
or why it made none (skipped because the last one was still open, or refused by the board);
*Settings*, its form, written on the spot. On a phone the one picked takes the whole screen,
with a way back to the list. The runner keeps a line per occurrence in `ponos.db` for this;
the tickets made before it did are found by its history and by their dated title
(`web/lineage.py`), and the times it made none before it are not known.

*New schedule* and the name of a row open the window that writes the six columns a schedule
is written in — the cadence, the hour, the day, the tick, and the project, model and priority
the ticket inherits — as buttons rather than selects: the day only appears for a weekly or a
monthly one, the hour is a time field, and a line under them says when the next ticket is born.
Never `Next`, `Last` or the ticket the last occurrence made: those are what the *runner* writes
back, and a console that let you edit them would let you make an occurrence happen twice.
A row nobody can read says what is wrong with it instead of a date it does not have, a
row turned off says *paused* rather than the date the runner last left on it, and
`runner.schedule = false` is said at the foot of the page, because a browser is the one
place that switch would otherwise be invisible — with *Turn it on in the settings*, which opens
the settings on that switch, focused. The page asks the board when you open it
rather than living on the event stream — a schedule moves four times a day at the very
most, and a tab left open on the board has no business polling that database.

<a id="statistics-on-the-dashboard"></a>**Statistics** sit at the top of the dashboard, over the board — a band you fold into
one line with the arrow beside its name, and that stays folded on that browser. It is what
the runner got through over a period: the last seven days when you open it, or the last
24 hours (yesterday and today: the figures count in days), thirty days, everything since the
board's oldest ticket, or two dates of your own. Four cards: the tickets **open**
on the evening of the last day (every column but *Done*, *Validated* and *Cancelled*, *Blocked*
included — so a period that ends today says what the board says), those **closed**
(moved to *Done* or *Validated*) and those **created** in the period, and what the sessions
**spent**. Under them, the **activity**: one chart, the tickets created and closed as two bars a
day and the open stock as a line over them — on its own scale, on the right, when it is of
another size than the bars —, every figure of a day under the pointer. Beside it, the tickets
**created, by type and sub-type**: bars a day (a week past a month) stacked by sub-type, written
as the board writes them in English, a ticket with none as *Unclassified*; a type to pick (Code
by default) and, on the dashboard, a project. Next to it, the **regression rate** — the bugs
over the bugs, features and improvements created —, with an arrow against the period of the
same length just before; with every project, a small table says which one breaks the most, and
a click on its row shows it alone. Last, the tickets created in the period, by project. A ticket is dated when it was created, never when its status changed, so a closing
is dated by the runner's history (in `ponos.db`) when the runner made it — a pull request
merged from *Validated*, a document written or published — and by the page's last edit
otherwise: a ticket you dragged to *Done*, or one closed because you merged its pull request
yourself. The *Closed* card says, under the pointer, how many closings each one dated. The spend is the
history's too: the `Cost` column says what a ticket cost, not on which day. The board they are
counted on is the one the console last read for its live view — at most twice `web.poll_seconds`
old —, so changing the period or the project redraws the figures without reading the board again. Under them, the
**blocks, by cause and week**: one bar a week, stacked by family, and beside it every
cause of the period with its count — see [Why a ticket stopped](tickets.md#why-a-ticket-stopped) —, and the
**code tickets done, by sub-type and week**, with the average cost and duration of each sub-type —
see [The sub-type of a code ticket](board.md#the-sub-type-of-a-code-ticket). Both are folded behind a *Show more* button, on the dashboard and on a project's page alike, and stays as you left it in this browser. The page they used to have is gone, and its old address,
`/?view=console/statistics/list`, leads to the dashboard.

**Exporting the cost, to re-bill a project.** *Export (CSV)*, beside the period, downloads one row per
session ended in that period — on the dashboard, every project's; on a project's page, that project's. The
columns are `date`, `ticket`, `lien`, `type`, `sous-type`, `modèle`, `statut final`, `durée (s)`,
`coût (USD)` and `PR`, and the `coût (USD)` column adds up to the cost the card shows for the same
period. The same file is `GET /api/spending.csv?project=<id or name>&month=2026-10` (`from=` and `to=`
instead of `month` for any other period; no `project` for the whole board). It is UTF-8 with a
byte-order mark, so a spreadsheet reads the accents; commas and quotes in a title are quoted.
From a terminal, `ponos history --csv --project <name> --month 2026-10` prints the same rows
(`--since`/`--to` for another period). It has no board to read, so it selects by the project each
session carried when it ran, and leaves `type` and `sous-type` empty.

**Settings** is `config.toml` drawn as a page — the same file, the same keys, and every one
of them, from the languages down to the channels. An example token — `xxxx` — is shown as
*not set* rather than as a token. It is
still a file you can open in an editor: the console rereads it when it changes on disk, and
what you save here keeps the comments that were around the line.

Each section of the file is a page of its own, and the one you are on is in the address:
`/?view=console/settings/read/config/notify` is a link to the notification settings that
you can send to somebody. Only that section is drawn, and what you typed in one you left
is given back when you come back to it. `[github]` is the section you add rows to rather
than fields you fill, so it is a table under that page, with its own *add* dialog and a
confirmation before a row goes.

The sections follow what you are trying to do rather than the tables of the file — *Running
tickets*, *Models and usage*, *Repositories and pull requests*, *Notifications*… — from the
connection to your board down to the names a hand-built board may spell differently. A field
says what it changes, in words, with its unit; a choice shows what each value does
(*One commit (squash)*) while the file keeps saying `squash`; and the key the field writes
sits under it in small, so the page and this guide's table can be read side by side. The
settings few people need are folded away at the bottom of each section, behind *Show the
advanced settings* — still in the form, so what you typed in one is saved with the rest.

Three things it does that a form usually does not.

- **A blank field says nothing**, and the runner's own default answers — shown greyed, in
  the placeholder. Clearing a field *removes the line* rather than writing an empty one, so
  "you chose thirty minutes" and "nobody said, so thirty minutes" stay two different
  statements. It is also how a board tells the runner it has one column for two moments:
  see [The statuses](tickets.md#the-statuses).
- **Your tokens stay on the machine.** A secret goes to the browser as *set, ending in
  …f3a2* and comes back only if you type a new one — an empty box means "leave it alone",
  so forgetting one is a button of its own. What you type is sealed in Ponos's vault, never
  written to `config.toml`, and the field names its variable rather than a key of the file.
- **A save is all of it or none of it.** The edits are made on a copy beside the file, the
  copy is loaded — if it would not parse, or would leave a working installation unable to
  run, nothing moves — and only then does it take the file's place, in one rename and with
  its permissions. The file it displaces is kept as `config.toml.bak`. A value the loader
  would have quietly repaired, like an interval of zero, is refused here with the reason
  rather than saved and silently changed.

Each section carries the command that checks it — `> doctor` for the board, `> notify` for
Telegram and Slack — because the CLI already knows how to say whether a token works, and a
settings page does not need a second opinion. The commands that change the machine rather
than read it — `run`, `update`, `service`… — are the terminal's. A setting that needs more than saving says so, once, and only when it moved.

**In English, or in French.** The console reads the browser before it says anything —
`Accept-Language` is a setting somebody actually made — and where the browser says nothing
useful, the time zone answers for it: a machine set to Europe/Paris is a machine whose owner
reads French. So there is nothing to choose, and the select at the top of *Settings → Web
console* is how you disagree with the guess. The choice is one line in
`localStorage`, like the theme, and it holds for every page of the console: the menu, the
board's own words, a ticket's page, and the settings tab down to the sentence under each
field, and what the server refuses with — « Rien à modifier. » rather than *nothing to change*, and
« Le serveur a répondu 502 » when it said no sentence at all; a refusal the console does not know
yet is shown in the server's own words. The pages before the console — the first connection, the sign-in, the token — are
drawn by the server and read `Accept-Language` the same way. What is *not* translated is what belongs to somebody else — a ticket's title and the
columns of your board are the board's own words, the output of `> status` is the CLI's, and a report a run
wrote is in the language [`runner.language`](configuration.md#the-rest-of-the-file) asked for.

### The Context page

Everything a session is given besides its ticket lives on one page, **Context** in the menu (and
in the command palette, Ctrl+K). It is a page of tabs — the tab you are on is in the address, so
`?view=console/context/read/context/vault` is a link you can send — and each tab is fetched when
you open it:

| Tab | What it holds |
|---|---|
| **Context** | the global context: the standing text every ticket is told first, for all the projects. Folded to a few lines, *See all* reads the rest, *Edit* writes it in place with the editor the brief uses; leaving with something typed asks first |
| **Memory** | what Ponos remembers from one session to the next — see [Memory](#memory) below |
| **Library** | reference files kept for the sessions — see [Library](#library) below |
| **Skills** | the Claude Code skills Ponos gives its sessions — see [Skills](#skills) below |
| **Vault** | Ponos's own vault — the keys, logins and notes the sessions are given, [kept encrypted](configuration.md#ponoss-own-vault-context--vault). An admin's: for a member or a reader the tab is not there, and the API answers 403 |

The context used to sit beside the Projects page, and the vault was a tab of Settings; the
Projects page no longer carries the context, and the old address `settings/vault` (and
`?page=context`) leads to the new page. More tabs will join these.

#### Memory

Every session starts from nothing but the global context, so a preference given in answer to a
ticket, a decision, a constraint of a project would be lost, or said again. **Memory** keeps them as
short facts, in `ponos.db`: a **type** (*person*, *preference or instruction*, *project*,
*reference*), a **scope** (all the projects, or one), a **source** (a ticket, a conversation, or typed by
hand — with a link back to the ticket or the conversation) and its dates. A fact is 300 characters at
most.

The tab lists them, filtered by scope, type and state (*accepted*, *waiting*, *refused*) and searched by
a word; *Add a memory* writes one (accepted at once), the pencil rewrites one, the bin deletes it.

**What reaches the sessions.** Only the *accepted* memories: those of the ticket's project and the
global ones, in a `# What you remember` block of the prompt, within 3 000 characters (the project's
first, the most recently touched first; the prompt says how many it left out). Another project's are
never in it. The console's assistant is told the global ones when a conversation opens.

**What a session proposes.** Every ticket may end its report with up to three
`MEMORY: <type> | <project|global> | <fact>` lines. They are *proposals*, shown at the top of the tab
with *Accept* / *Refuse*: nothing is read by a session before you accept it. A refused proposal stays
known, so the same fact learned again does not come back. *Accept the proposals without waiting*
(under the list, an admin's) lifts the rule: a proposal is then kept at once, and you read it
afterwards.

**One memory, not two.** The console's assistant keeps files of its own
(`~/.claude/projects/<workspace>/memory/`, one per fact). When some are not imported yet the tab
offers *Import n file(s) of the assistant*: each file's description becomes a global memory, once —
importing again adds nothing, and the files are left as they are. From then on this tab is the memory
the sessions, the assistant's opening frame and the [MCP server](#connect-ponos-to-claude) read.

Over MCP, `list_memories` (read) lists them and `propose_memory` (write) proposes one — it waits like
the others. The API is `GET /api/memories`, `POST /api/memories`, `PUT`/`DELETE
/api/memories/<id>`, `POST /api/memories/<id>/accept` and `/refuse`, `POST /api/memories/import`;
the acceptance setting (`POST /api/memories/options`) is an admin's.

#### Library

A console attachment belongs to one conversation and is kept `web.attachment_days` (7). The
**Library** is the place for what has to stay: a charter, a contract, a brief, a quote, screenshots, a
CV. Drop files on the tab or use *Add files*; each one has a **name**, a **description** (what it is,
and when a session needs it), **tags** and a **scope** — all the projects, or the few that are ticked.
The pencil renames it (the extension stays), describes and tags it and moves it to another scope; the
arrow downloads it; the bin deletes it. Images and PDFs have a *Preview*. The list is searched by a
word of the name, the description or the tags, and filtered by project (what that project's sessions are
told) and by tag; *List* and *Thumbnails* are two views of it, and the choice is kept by the browser.
Only the kinds of file a conversation takes are accepted (images, videos, pdf, txt, md, csv, json, docx,
xlsx — never HTML or SVG, since the files are served back from the console's own origin).

The files are in `~/.local/state/ponos/library/` (`0700`, never in a repository), their metadata in
`ponos.db`, and nothing expires. A file may weigh `web.library_max_mb` (50 MB by default) at most;
`ponos doctor` and the settings say how many files the library holds and the room they take.

**What reaches the sessions.** A `# Reference files` block of the prompt lists the files in the scope
of the ticket's project — their absolute path, their name and their description — within 3 000
characters (the prompt says how many it left out). The session reads one from its path with the tool
it reads source with; nothing is copied into the worktree. A file for project X is in no other
project's prompt, and a ticket with no project is told the files for every project only.

**From a conversation.** A file you sent in a conversation shows a bookmark when you point at it:
*Keep in the library* copies it there, with no scope (all the projects), ready to be described.

Over MCP, `list_library` (read) lists the files, for a project or a tag or a word, with their path, and
`get_library_file` reads one file's metadata — never its content. The API is `GET /api/library`,
`POST /api/library/upload?name=…` (the raw file as the body), `PUT`/`DELETE /api/library/<id>` and
`GET /api/library/<id>/file[?download=1]`.

#### Skills

A session is a Claude Code session, and Claude Code loads *skills*: a folder `.claude/skills/<name>/`
with a `SKILL.md` (a frontmatter with `name` and `description`, then instructions) and any files
beside it. **Skills** is where Ponos keeps the ones it gives its sessions, so that you see and choose
what a session receives instead of committing them in every repository.

The tab lists each skill with its **name**, **description**, **scope** (all the sessions, or the
projects it is limited to) and **state** (*active* or *inactive*). *New skill* writes one: a name
(lower case, digits and hyphens), a description — what it is for and when Claude should use it, which
is what Claude reads to decide —, the body of the `SKILL.md` in the Markdown editor, and the scope.
The pencil edits it and attaches or removes the files beside the `SKILL.md`; *Disable* keeps a skill
but stops giving it; the bin deletes it. *Import a folder* and *Import a .zip* read a skill that
already exists (the folder or the archive holds a `SKILL.md`, at its root or one level down; the name
comes from its frontmatter, or the folder's name). Keys of the frontmatter Ponos does not edit
(`allowed-tools`, for instance) are kept when you save.

**Where they are kept.** In `ponos.db` (tables `skills` and `skill_files`): a skill is a few small
files that the console writes and the runner reads, and the database keeps them in one transaction
with their row, follows the backup of `ponos.db` and has no path on disk to validate. A file is 1 MB
at most, a skill 100 files and 5 MB.

**What reaches a session.** When a ticket's session starts on a repository, the active skills whose
scope covers its project are written in its worktree, under `.claude/skills/<name>/` — the worktree of
the ticket only, never the project's own checkout. Each folder carries a `.gitignore` made of `*`, so
that the skills are in no commit and no pull request. A worktree picked up again has its skills
redone, and a skill disabled since is removed from it. Another project's skills are never there.

**The repository wins.** A skill the repository already provides (`.claude/skills/<name>` in the
worktree) is never overwritten: Ponos's skill of that name is not placed for that project, the run
says so, and the row shows a warning naming the projects concerned. Below the list, *In the
repositories* shows, read only, the skills the projects' clones hold, each with the project and
repository it comes from.

Over MCP, `list_skills` (read) gives the same lists. The API is `GET`/`POST /api/skills`,
`GET`/`PUT`/`DELETE /api/skills/<id>`, `POST /api/skills/<id>/files` and `DELETE
/api/skills/<id>/file?path=…`, and `POST /api/skills/import`.

### Goals

**Goals** is the [goals database](board.md#the-goals-database--what-the-ticket-is-for) drawn as a page:
one card per goal — its status, its due date, its name, what it means, the projects it is for, and **« n of m tickets
done »**, written in words over a bar. A goal no ticket points at yet says **« No ticket tied
yet »** (« Aucun ticket rattaché ») instead, with **Tie tickets** — its form, opened on the
*Tickets* field — and **New ticket for this goal**, the form with the goal already chosen. The count is the console's: the
tickets of the board that point at the goal, the cancelled ones left out. The list rests on the active goals (no `Statut`, or
`actif`); its filters are the status — *All statuses*, or any one the database holds — and a
project. The cards come soonest due first, the goals without a date last, and among the same day
the highest priority first. Beside its due date, an active goal whose day is past says **« Late »**
(« En retard »), and one due within a week **« In n days »** (« Dans n jours ») — *Today* on the
day itself; a goal reached or given up says neither. It follows the event stream: a goal written in another tab, a ticket tied to one, or a
ticket of a goal moving to *Done* reads the list again, and the count moves without a reload.
The list is answered from what the console already holds, so it opens at once: a goal written
elsewhere — the MCP, another tab — shows a moment later, once the read the console makes behind the answer finds
it, and a console that has not read its board yet shows the goals first and their counts
when the board is in.

#### How a goal's tickets are counted

One rule, the same on the page, in its drawer, in a project's *Goals* box and in the MCP
connector's `list_goals`:

- **done** is the tickets in the `done` column —
  not *In review*, not *Validated*: a ticket counts once its pull request is merged or its page
  published;
- **the total** is every ticket that points at the goal **but the cancelled ones** — drafts,
  tickets with no status, blocked and failed ones included: a cancelled ticket is work given
  up, not work left to do;
- **only the first goal of a ticket's `Objectif` relation counts**, as only the first is read
  into its prompt: a ticket tied to two goals adds to the first one alone. The console only
  ever writes one goal on a ticket.

So a goal with two tickets done, one cancelled and one ready says « 2 of 3 tickets done ».

A card opens the goal's page in a drawer over the list: its description, *Done when*, priority
and projects, the count, and its **tickets grouped by column** in the board's order, each with
its short number and a link that opens its window over the page. **+ Ticket** opens *New ticket*
with the goal already chosen.

**Everything is written from there.** *New goal* opens the form the database is written in —
name, description, *Done when*, due date, status, priority (a score from 0 to 100, as on a
ticket; left empty, the column is not touched) and projects. *Edit*, on the card or the page,
opens the same form on the goal, with one more field: its **tickets**, tied or untied in a
multi-select. A ticket is also tied from its own side: its window shows its goal under the title,
a link to the goal's page, and a select to change it or set *No goal*. That select, like the one
of *New ticket*, offers only the goals still worked toward — those of the ticket's project first,
then the others —, plus the one it already serves; it is not there at all on a board with no
`Objectif` column. The count is read again after every write, and a write the board refuses is
shown as it was said.

An empty list shows *No goal.* with the *New goal* button.

**A goal that is over is closed, not deleted.** *Reached* and *Given up* write its status
(`atteint`, `abandonné`): the goal keeps its page, its tickets and its count (« 12 of 12 done »),
and the list no longer shows it unless asked. *Delete*, set apart, asks first and sends the page
to the board's trash (flagged in `ponos.db`, never erased); its tickets stay where they
are and serve no goal.

### Ideas

Ponos can also propose what to do next. From the dashboard the ideas are the workspace's —
new projects, or improvements that cut across them; from a project's page they are that
project's. One short session writes ten at once on `runner.ideas_model` (`haiku` unless you
say otherwise), given the project's brief, its README when the clone has one, its latest
tickets and, for the workspace, the list of projects. The [goals](#goals) being worked toward go
in too, under « Les caps du moment » — the name, `Critère` and `Échéance` of each active one
whose `Projets` holds the project, or of all of them for the workspace —, in the prompt of the
batch and in the scoring's, whose grid does not change; with no active goal the prompt is the
one it was before. Every idea already proposed for the same
scope is in the prompt too, and a title too close to one of them — or to a ticket — is dropped
on the way in: an idea thrown away is never proposed again.

An idea is *new*, *kept*, *thrown away* or *turned into a ticket*. Turning one into a ticket
writes it onto the board as a draft with no model, under *What*, *Where*, *Done when* and *Out
of scope*, attached to its project; for the idea of a new project it creates the project, its
description as the brief, and a first draft ticket to frame it. Keeping one only marks it worth
doing, and throwing one away only marks it so: nothing is ever deleted. The last choice can be
taken back — an idea's ticket stays on the board as a draft, and is what it becomes again if it
is turned into a ticket a second time.

Each idea also has a category, one and only one: *UX/UI* (the interface and how it feels),
*Feature* (something new worth something to whoever uses the project), *Security* (a flaw or
a risk, to deal with first) or *Technical* (refactoring, performance, technical debt — so that
*Feature* does not become whatever is not something else). Ponos is asked to choose one for each
idea it proposes; one it left out, and those proposed before categories existed, stay
unsorted until somebody picks one in the idea's form.

Each idea also has a relevance score, from 0 to 100, in a coloured circle at the top of its card
and of its card in the pile: **green** from 70, **orange** from 40 to 69, **red** under 40 — the
number is always written, so the colour is never all it says. Ponos gives it with the idea, by a
grid written in the prompt: impact for whoever uses the project or for the business (40 points),
fit with the brief and the context (25), gain against effort (20) and originality, against the
tickets and the ideas it is shown (15) — and one line that says why, in the tooltip, on the pile's
card and in the idea's page. A score that is missing or not a number is *Not scored*, in grey,
never a zero. An idea written by hand (*New idea*, or `create_idea` over MCP) is scored once it is
saved, behind the form, by `runner.classify_model` (`haiku`) with the same grid; its circle says
*…* until then. The ideas from before scores, and those whose scoring failed, are scored from
*Score the unscored ideas* on the *Ideas* page: it says first how many there are, on which model,
in how many calls (twenty ideas to a call, one scope per call) and the most it may cost — each call
is stopped at $0.10 — then scores them in the background, the list filling in as each call ends.
The two thresholds are `GREEN` and `ORANGE`, in `ideas.py` and in `frontend/src/lib/idea-search.ts`.

Each idea says who wrote it: Ponos, with its mascot, or a person — ideas can be written by hand
— by the name and picture of the GitHub account `gh` is signed in as (git's `user.name` when
there is no `gh`). An idea reworded by hand also says who last changed it, and when.

In the console the dashboard's *Ponos, find me ideas* and a project's *Find me ideas for this project*
open the same pile of cards, one idea each: swipe right (or drag, press ♥, or →) to keep, left
(✕, ←) to throw away, *Undo* for the last card. Ponos waits while a batch is written, and at the
end of the pile *Ten more* asks for another. Swiping right turns the idea into a ticket at once.
The *All ideas* tab lists every idea of the scope, thrown ones included. On a phone the pile
fills the screen.

**Ideas on a schedule.** Ponos can also look for ideas without being asked: *Settings*, beside *New
idea* on the Ideas page, opens the window that sets it (the same keys are the `runner.ideas_*` lines of
`config.toml`, each documented in `config.example.toml`, and a card of the settings page). Off by default;
otherwise every 4 hours, every day at an hour, every week on a day at an hour, every N hours, or a
five-field cron line (`0 9 * * 1-5`). The moments come from the engine of the recurrences
(`schedules.next_occurrence`, plus `schedules.every` and `schedules.cron`) in this machine's timezone, and
follow its rule: the first moment of a new schedule is waited for, and a console that was off for days
finds one pass due, not one per missed moment. Passes run in the console (`ponos service run`), which holds
what a batch is built from; `ponos doctor` says so. *All projects* covers the ones added later too,
*Selected projects* the ones ticked (`ideas_projects`, by page id or name); the workspace's own ideas are
a switch of their own (`ideas_workspace`), and a project's *Settings* tab can turn it off or on for itself
(kept in `ponos.db` with its other `project_settings`, and it wins over the file). Guard-rails: ideas per
pass and per project (`ideas_per_batch`, 10), a project with `ideas_skip_above` new ideas nobody sorted
(20, 0 for never) is skipped and the journal says so, `ideas_budget_usd` stops a pass between two projects
once it has spent that much (0: no ceiling), `ideas_model` as before, and `ideas_notify` sends “n new
ideas” to Telegram and Slack. The page shows the next pass and the last one (when, how many ideas, the
projects skipped), and the recurrences' calendar draws the passes to come, read only
(`GET`/`POST /api/ideas/schedule`; `idea_schedule.py` knows when and who, `web/planned.py` does it).

A project's page has an *Ideas* tab, beside *Tickets* and *Brief* (`&tab=ideas`): every idea of
the project with a count per status, and filters by status, by category, by score colour (green,
orange, red or not scored) and by author (Ponos or us), and an order: *Most relevant first* (the
highest score first, those not scored last — where the new ideas rest) or *Newest first* (where
every other list rests). Each card puts its score and its title first, then where it stands, its category and what it is (a ticket,
or a new project),
a few lines of its description, and who wrote it and when, small. It has one gesture in plain
sight — *Turn into a ticket* (*Create the project* for the idea of one), or *Open the ticket* once
it is one, and the toast that says it was made offers it too — and the others a click away: the pencil rewords it, and the *…* menu keeps it,
throws it away or makes it new again. Its title opens it whole, beside the list, with what it
should touch, *Done when* and *Out of scope*. *New idea* opens a quick-entry window, as tall
as its few lines (a sheet up from the bottom on a phone): whom it is for in a menu at its top
(the page's own project, already picked; *Propose a new project* at the bottom of that menu makes
the idea a project-creation ticket), the title with the cursor in it, a few lines of description,
and the category as chips. *Create the idea* — or Ctrl+Enter (⌘+Enter) — waits for a title;
*Create another* leaves the window open and empty for the next one. The idea is stored as written by
hand; *Find me ideas for this project* is there too. The deck's *All ideas* tab is the same list,
the workspace's when opened from the dashboard. Cards or a table, whichever you pick.

The *Ideas* entry of the menu is that same list for every scope at once: each card also says
whom it is for — the project's icon and name, or *Workspace* — and a filter by project sits
beside the filter by status. The filters live in the address (`filter=…`), so a link or a
reload opens the same list. *New idea* sits at the top of the list, and on an empty one. *Ponos,
find me ideas* asks for a batch for the project picked in that filter, and the swipe it opens
stays the quick way to sort them. The console reads the list through `GET
/api/ideas/all?scope=all`.

On a phone the head of a list keeps to a few lines, so its first row is on the screen without a
scroll: the sentence under the title and the icon beside it are left out, the layouts are their
icons, and the filters fold behind one *Filters* button — the search of the *Schedules* beside it,
the status of the *Ideas* as a single button with its count. The Ideas' other gestures —
*Ponos, find me ideas*, *Score the unscored ideas*, *Settings* — and the line that says when Ponos
looks next are behind the **⋯** beside *New idea*. On the *Settings* page, the card that only
named again the tab just picked is left out.

Ideas live in the local database, `ponos.db`, with what each batch cost, who wrote them, and
when their status last changed, and their score (migration `ideas_have_a_score`: a `score`
column, NULL for not scored; the reason is kept in the idea's detail) — they survive restarts and
updates. The console asks for them
through `GET /api/ideas[?project=…]` (the pile, and the last fifty decisions), `GET
/api/ideas/all[?project=…]` (every idea, and the count per status), `POST /api/ideas` (one written
by hand), `POST /api/ideas/<id>` (reworded), `POST /api/ideas/generate`, `POST
/api/ideas/<id>/keep`, `…/discard`, `…/ticket`, `…/reopen`, `POST /api/ideas/undo`, `GET
/api/ideas/unscored[?scope=all|project=…]` (how many have no score, and the ceiling) and `POST
/api/ideas/score` (score them). Every idea it reads carries `score`, `score_reason`, `tone` and
`scoring`.

### Keeping it running

It already is. `install.sh` arms the console's unit along with the daemon's, and
`ponos service on` does the same on an installation that predates this — so the
console is up on `http://127.0.0.1:8787` with nothing to type, and comes back with the
machine.

```sh
ponos service run --print-token   # the token, if you lost the URL
systemctl --user stop ponos-web   # stop it until the next boot
ponos service off                 # stop the daemon and the console for good
ponos service status              # how the daemon, the console and the Tailscale unit stand
```

What it opens is loopback, which is why it can be a default: the port is reachable from
this machine and from nowhere else. Widening it is still a decision, and the next section
is why. `TR_NO_WEB=1 sh install.sh` installs the unit and leaves it stopped.

### What is behind that port

**The console is arbitrary code execution on the machine that runs it.** The chat starts
Claude Code sessions with the same `bypassPermissions` the runner uses — that is what
makes it useful, and it is the whole of the risk. So:

- it binds **`127.0.0.1`** and `serve` **refuses any other host** unless `PONOS_WEB_TOKEN` — or
  the sign-in below — is set on purpose: a token drawn automatically
  is not a decision you took;
- every request carries that token — the `?token=` in the URL is moved into a cookie on
  the first load, so it stops sitting in your history — or the cookie that signing in
  leaves, which is the same guard reached by a different door. The cookie is named after
  the port (`ponos_token_8787`): a browser keeps cookies by address, not by port, and two
  consoles on one machine — the demo and the real one — each keep their own;
- `serve` never prints that token: what it says lands in `journalctl` and `docker logs`,
  so a console opened by its token shows `/?token=…` and sends you to
  `ponos service run --print-token` (`docker compose exec ponos ponos service run --print-token` in the image);
- writes demand a header a cross-origin form cannot set, and the `Host` header must name
  the address the console was reached on. Between them, a hostile page you have open in
  another tab can neither post to the console nor read from it;
- a wrong password, installation code or token — in the address or a header — is counted
  **per address**, in memory: the address waits 1 s, then 2, 4… up to 30, and the tenth
  failure in a row locks it out for 15 minutes. An attempt is counted *before* it is
  checked, so twenty sent at once are one checked and nineteen refused with a `429` and a
  `Retry-After`. Behind a proxy declared in `web.trusted_proxies` — this machine by default,
  which is where `tailscale serve` relays from; Traefik by its address — the address is the
  last one it appended to `X-Forwarded-For`. Anybody else is counted by its own address,
  whatever it says it relays;
- the password is kept as a scrypt digest, and a sign-in lasts thirty days from its last use
  (`ponos service run --sign-out-everywhere` ends them all, and signs out the MCP connectors too);
- every page is served under a **Content-Security-Policy** that runs no script but the
  bundle's files from `/static/` and the few lines a page carries inline, allowed by their
  hash; styles are the bundle's files too, plus the ones its libraries write at runtime (the
  toasts, a dialog's scroll lock, the editor) — a style runs no code. The API answers under
  `default-src 'none'`. With them, `Permissions-Policy` (no camera, no location; the
  microphone for this origin only, for dictation), `Cross-Origin-Opener-Policy` and
  `Cross-Origin-Resource-Policy: same-origin`, and `Strict-Transport-Security` once the proxy
  says the browser came in over HTTPS — never on plain HTTP;
- a repository named on a project page is checked to be `owner/name` before `gh` or `git`
  sees it, and passed after `--`: a page anybody can edit names nothing a command line would
  read as an option.

To reach it from your phone or another machine, **tunnel rather than widen**:

```sh
ssh -L 8787:127.0.0.1:8787 <the machine running it>
```

Then `http://127.0.0.1:8787` on the near side, over a channel that already authenticates
you. A console bound to `0.0.0.0` with a token is possible — set `PONOS_WEB_TOKEN` and say so —
but the tunnel is the answer that does not depend on the token never leaking.

[Tailscale](https://tailscale.com) does the same without a terminal on the phone:
`tailscale serve --bg 8787` relays `https://<machine>.<tailnet>.ts.net` to the loopback
console, inside your tailnet only. Set `web.url` to that address — the console answers the
name `web.url` gives it, that one exactly, and still turns any other away with a 421.
Never `tailscale funnel` on the console itself: that one is the whole Internet. The one
thing that has to be public is the MCP connector, and `ponos tailscale` below does exactly that.

#### From your phone, and from Claude: `ponos tailscale`

Claude's connectors are called from Anthropic's servers, which are not on your tailnet. So two
doors, kept apart: the console stays private, the MCP endpoint alone goes through
[Funnel](https://tailscale.com/kb/1223/funnel), behind the OAuth sign-in of the
[connector](#connect-ponos-to-claude). Funnel is per host *and port* — which is why they are on two
ports.

| Door | Address | Who reaches it |
| --- | --- | --- |
| Console | `https://<machine>.<tailnet>.ts.net:8443` | your devices on the tailnet |
| Connector | `https://<machine>.<tailnet>.ts.net/mcp` | the Internet — `/mcp`, `/oauth`, `/.well-known` and `/api/hooks` ([incoming triggers](tickets.md#a-ticket-that-comes-from-a-tool-incoming-triggers)), no other path |

1. **On the laptop**: install [Tailscale](https://tailscale.com/download) and `sudo tailscale up`. In
   the [admin console](https://login.tailscale.com/admin) enable *MagicDNS* and *HTTPS certificates*
   (DNS page), and allow Funnel for this machine (the `funnel` node attribute — the Access controls
   page offers it in one click).
2. **On the phone**: install the Tailscale app and sign in with the same account. Then open the
   console address above and sign in with its email and password.
3. **Set `web.url`** to `https://<machine>.<tailnet>.ts.net` (no port), then
   `systemctl --user restart ponos-web`.
4. **Publish**: `ponos tailscale enable`. `ponos tailscale` (status) prints both addresses and says
   whether they are up.
5. **In Claude** (claude.ai or the mobile app, *Settings → Connectors → Add custom connector*):
   paste `https://<machine>.<tailnet>.ts.net/mcp`. Claude opens the console's sign-in page — sign in,
   choose *read* or *read and write*, and call the `whoami` tool to see it hold.

The unit is `ponos-tailscale.service`. It looks every 30 seconds: while the laptop sleeps, changes
network or is logged out of the tailnet it waits, and as soon as the tailnet is back it checks the
serve configuration and puts it back if it drifted (`tailscaled` reconnects by itself — this is only
for the configuration). `journalctl --user -u ponos-tailscale -f` tells what it did. Nothing turns it
on but you: not the installer, not an update, and `ponos service off` turns it off.
`ponos tailscale disable` also takes both doors down in Tailscale. Without systemd,
`ponos tailscale watch` does the same in the foreground. As a second lock, the console itself
answers 404 to any path but those three on a request that came through Funnel.

| Key | Default | Effect |
| --- | --- | --- |
| `web.host` | `127.0.0.1` | what to bind. Anything else needs `PONOS_WEB_TOKEN`, or a sign-in, set |
| `web.port` | `8787` | |
| `PONOS_WEB_TOKEN` | | not a key of this file: the secret is in Ponos's vault or the environment (see [Configuration](configuration.md#configuration)). Unset: drawn once into `~/.local/state/ponos/web/token` |
| `web.email` | `""` | with a password: what the console asks for instead of the token |
| `PONOS_WEB_PASSWORD` | | not a key of this file: the secret is in Ponos's vault or the environment, which wins (see [Configuration](configuration.md#configuration), and below) |
| `web.poll_seconds` | `15` | how often the console asks the board what changed (a two-minute overlapping window; the whole board every five minutes) — only while a browser is connected; a page asking for the board meanwhile (dashboard, goals, statistics) is served that last read, unless a write from the console came after it. `GET /api/board` answers that last read whatever its age, reads the board again behind the answer once it is older than this, and keeps it on disk so that a console just restarted answers at once; it carries only the 50 latest tickets of *Done* and of *Cancelled* — `hidden` counts the others, `?closed=all` gives them all. The console's own columns come from the event stream, whole |
| `web.chat_timeout_minutes` | `20` | past this, a chat turn is killed |
| `web.chat_model` | `""` | the model a new conversation starts on (`opus`…, or an OpenRouter slug); empty: `runner.model` |

### The first connection

A token protects an installation that is already set up. A fresh one has nothing to
protect yet — and asking somebody to go and find a secret on disk before they may type
their own is the wrong way round. So a console **nobody has claimed** — no `PONOS_WEB_TOKEN`
chosen on purpose, no email and password set — serves its first connection
instead of a door, and `http://127.0.0.1:8787` is the whole of the address. It comes in
steps, drawn by the console itself, one write each:

1. **Language** — the console's, and the one the reports are written in. Taken in the
   browser at once, and written to the file (`runner.language`, `runner.app_language`) with
   the account — or straight away when there already is one.
2. **Access** — the email and the password the console asks for from now on. They are
   written into `[web]`, the browser is signed in with them there and then, and that pair
   is what **closes this step for good**: from the next request on, the console is
   claimed. From anywhere but this machine, the *installation code* is asked first — see
   below.
3. **Claude provider** — who answers the sessions, in three cards: the CLI signed in as you,
   an Anthropic key, or OpenRouter (see [Who answers the sessions](configuration.md#who-answers-the-sessions)).
   A key is tried against its provider before it is written. The CLI is asked the moment its
   card is chosen, as `ponos doctor` asks it: not installed, the step gives both commands —
   `curl -fsSL https://claude.ai/install.sh | bash`, then `claude auth login`; installed but
   not signed in, the second one; signed in, a green tick and the account. *Check again* asks
   once more after you have typed them, and a link moves to an Anthropic key for whoever would
   rather not install the CLI.
4. **GitHub** — the GitHub App in one click, or whether `gh` is signed in, or has a
   `GH_TOKEN`, and as whom.
5. **First project** — the repositories found under `runner.workspace_root` (the folder is
   created when a fresh machine has none), each one click from being a project; or a GitHub
   repository, cloned at the first ticket; or a project with no code at all.
6. **Channels**, optional — Telegram and Slack. Leave Telegram's chat id empty, say anything
   to your new bot, and the id is read back from it, the same gesture as `notify --pair`.
7. **First ticket** — a short writing ticket, put on the board in *Ready* under the first
   project and **played at once** with `ponos run --ticket`, in a free place of the daemon —
   or by a run of its own when no daemon is up yet: the step follows it to *Review*, links it, and says *it works*. One that fails shows
   what its run printed.
8. **Summary** — what the console runs on, one line per thing that has to work, each `ok`,
   `missing` or `error`, and each leading to the step that changes it: this machine (git,
   Claude Code and its sign-in, the free disk, with the command that installs what is
   missing), the provider and its account or masked key, the default model and the automatic
   choice, the board and how many tickets it holds, the GitHub account, the projects folder
   and the repositories found in it, the channels, and whether this is a container or a
   machine, with the version. *Run the full diagnosis* below it runs `ponos doctor` and shows
   its text, with a button that copies it for whoever is helping. The **Settings** page keeps
   the same summary and the same button at its top, under *What this console runs on*.

<p align="center">
  <img src="../docs/media/first-connection/5-first-ticket-played.webp" width="420" alt="The first ticket step: the demonstration ticket played, and the console saying it works">
</p>

Every step but the account may be left for later, and a step that fails says so and leaves
the ones before it standing. `/setup` is where the steps are afterwards, and the bare address
of a fresh container whose steps nobody has gone through leads there on its own.

Once the console is claimed, *Back to the console* sits at the top of `/setup`, and each
step's pill is marked by the lines of the summary it answers for — a green check when they
are OK, an amber or red mark when one is missing or failing; the summary is read once per
visit, and again only after a step writes something. An installation whose summary is
OK on every line opens `/setup` on the summary rather than on the language.

`serve` starts on the file `install.sh` leaves: the board needs nothing, so the console only
refuses a configuration that is missing or does not parse.

> **Who may claim it.** On a laptop the console listens on loopback, and the first browser
> to arrive is somebody sitting at this machine. Anywhere else — another address, or this
> one *through a proxy*, which is what a domain in front of a container is — the first
> connection asks for the **installation code**: eight letters `serve` draws when it starts
> on an unclaimed console, and prints beside the address (`code  K7Q2-M9XD`). In a
> container that line is in its logs, which Dokploy shows. A wrong code costs a second, the
> right one opens the door once, and a console that drew none refuses a first connection
> from outside altogether. With `PONOS_WEB_EMAIL` and `PONOS_WEB_PASSWORD` in the
> environment the console is claimed before anybody arrives, and the steps start after
> the account.

An installation that already works and has never been given a password is unclaimed too,
and the same address serves the same steps. A browser
still carrying the token in a cookie goes straight to the console instead, and
`http://127.0.0.1:8787/setup` is where the steps are then.

### Signing in instead of pasting a token

A token is right for a machine and tiring for a person: it has to be found again on every
browser you open the console in, and the URL that carries it is a secret you paste into
your address bar. So the console can also be opened the way everything else is — with an
email and a password, which is what the first connection above writes for you, and what
these two lines say by hand:

```sh
# config.toml, [web]:              email = "you@example.com"
# the console's Settings:          the password you would actually remember, sealed in the vault
```

Or, on a server, without writing either of them down anywhere:

```sh
PONOS_WEB_EMAIL=you@example.com PONOS_WEB_PASSWORD=… ponos service run
```

The environment wins over the file and the vault, which is what makes it worth setting: a systemd
drop-in or a container carries the credentials, and `config.toml` stays a file you can
read out loud. Both halves are needed — an email without a password is somebody half-way
through configuring one, and it is not a way in.

With them set, `http://127.0.0.1:8787` is a bookmark that works: the page asks for the
two, and the session it leaves is signed from them rather than drawn, so a console that
restarts does not sign you out and **changing the password signs out every browser at
once**. A session lasts **thirty days from its last use** — a browser that keeps coming
back is renewed, one left in a drawer runs out — and `ponos service run --sign-out-everywhere`
ends every one of them, the running console's included, by drawing a new key into
`~/.local/state/ponos/web/sessions` — and takes back the keys of every MCP connector signed in
over OAuth, which a new password alone does not. A wrong answer is counted against
the address it came from, which waits longer after each — see *What is behind that port*.

Ponos's vault keeps the password as a **scrypt digest** (`scrypt:n:r:p:salt:hash`), never as
it is typed: the console's Settings write it that way, and the one a `secrets.env` from before
held in clear is digested as the next launch moves it into the vault — the same password
signs in, nobody is asked to type it again.
`PONOS_WEB_PASSWORD` in the environment may hold the password or such a digest; one in clear
is digested in memory when the console starts, and stays the unit's to keep.

The token does not go away. It stays what a script carries in `Authorization: Bearer`,
what `service run --print-token` prints, and what the dev server's proxy borrows — it just
stops being what *you* carry.

### Several people on one console

One password is one person: shared, everybody is the same somebody, nobody knows who
validated a merge, and an intern can force one. So a console can be **shared with
accounts**, each an email, a name, a password (kept as a scrypt digest, as yours is) and
one of three roles:

| Role | May |
|---|---|
| **Reader** | see the board, the tickets, the projects, the ideas, the goals and the schedules — and change nothing |
| **Member** | also write tickets, launch them, answer them, validate them, edit projects, ideas, goals and schedules, talk to the workspace |
| **Admin** | also change the settings and the vault in them — *Context → Vault*, which nobody else even sees listed ([Ponos's own vault](configuration.md#ponoss-own-vault-context--vault)) —, a project's own settings (its forced validation among them), the GitHub App, the ideas' schedule, the update, and the accounts |

**The sign-in of `[web]` is the first admin**, with nothing to migrate: it stays where it is,
heads the list, and cannot be demoted or deleted from the console by anybody it invited. The
token is the machine itself, and may do everything an admin may.

**An invitation is a link, not an email.** Ponos sends no mail: *Settings → Accounts* draws a
link for a role, you copy it and give it however you like. It opens a page asking for a name,
an email and a password, makes **one** account, and is good for **a week** — the console
keeps only its SHA-256, so it is shown once. A link not taken yet can be withdrawn from the
same page; a wrong code is counted as a wrong password is.

What the page offers follows the role: a reader is shown no button that would change
something — no *New ticket*, no Decide tab, no message bar, no chat, no drag — and the API
refuses the same writes with a **403** whatever a page sends. A member does not see the
Settings. A new role is the API's at once, and the page's at its next load; **deleting an account signs
out every browser signed into it**, from its next request (its live stream ends within
fifteen seconds), and nobody else.

**Who did what.** Once the console is shared, an answer or a decision written on a ticket
from the console says who: *Answered from the console by Léa. Decision: validated.* A move
leaves no comment — one on a blocked ticket would be read as an answer — so the console keeps
its own journal: every ticket created, moved, answered, decided, re-prioritised or tied to a
goal from the console is a line with the name, shown under the brief of the ticket's page
(*From the console*) and given by `GET /api/tickets/<id>/audit`. A console used alone writes
its comments as before.

A key for the MCP server (*Connect Ponos to Claude* below) is an admin's to give: signed in as
a member or a reader, the consent page asks for the console's own credentials.

---

<a id="driving-it-from-claude-the-mcp-server"></a>

## Connect Ponos to Claude

Ponos is an [MCP](https://modelcontextprotocol.io) connector: its address, and nothing else.

1. In Claude — claude.ai, Claude Desktop — *Settings → Connectors → Add custom connector*,
   with your console's address followed by `/mcp`: `https://<your console>/mcp`.
2. Click **Connect**: a Ponos window opens. Sign in if it asks, then **Allow**. No token to copy.
3. Ask *who am I on Ponos?* — `whoami` answers — then *what is waiting for me?*

In **Claude Code**, on the machine Ponos runs on, the same in one line — then `/mcp`,
*Authenticate*:

```sh
claude mcp add --transport http ponos http://127.0.0.1:8787/mcp
```

claude.ai and Claude Desktop reach the console from the Internet, so it has to be served over
HTTPS — behind Traefik on Dokploy (see [Install with Dokploy](server.md#install-with-dokploy)), a
reverse proxy or a tunnel. If what is in front of it does not set `X-Forwarded-Proto`, say the
address once in the settings — *Web console › Public address*, `web.url` — or claude.ai is
told `http://` addresses and refuses them. `ponos mcp` prints the address to paste, and
`ponos doctor` checks it.

**Already connected?** Nothing to do: the connectors added before keep their keys, and a
token drawn with `ponos mcp token` keeps working — it is still there for a client that cannot
sign in itself, as a header: `claude mcp add … --header "Authorization: Bearer <token>"`.

**Not sure how?** The console's **Settings › MCP** tab explains what an MCP is, gives the
command or the JSON block for Claude Code, Claude Desktop or another client with this console's
address already in it, and has a *Test the connection* button that says what is wrong — and
what to do about it — when a client could not connect. It also lists the MCP servers Claude Code
holds for the sessions (GitHub, Sentry…), each *connected*, *to sign in* or *failing*. It shows
no key; `ponos mcp token` stays a terminal command.

### What Claude can do with it

From claude.ai — on the web or on a phone — or from Claude Code, a conversation can see what
Ponos is doing, open a task, create one in the right project and answer the question a blocked
one asks: what the tools hand
back is a task, a project, an idea, an amount — never a page or a property.

| Tool | Title | Scope | What it does |
| --- | --- | --- | --- |
| `whoami` | Mon compte | read | the console, the email that opens it, the connected client and its access, where the board lives, how many projects and how many tasks wait for you |
| `list_projects` | Projets | read | the projects: name, icon, repository |
| `list_tasks` | Tâches | read | the tasks, each with its goal, filtered by project, by status, or `waiting_for_you` (the blocked ones) |
| `get_task` | Détail d'une tâche | read | one task: its goal, its mission, its result and its journal apart, the last turns of its discussion and the question it waits on, the pull request, the cost, the session, the last runs |
| `runner_status` | Runner et dépenses | read | the daemon, its places and its queue with why each task waits, the sessions in flight, the tasks running, what was spent today, over the period and project by project |
| `list_ideas` | Idées | read | the ideas of a project, or of the workspace, by state, each with its score and why |
| `list_goals` | Objectifs | read | the goals: status, due date, criterion, projects and progress — tasks done out of all but the cancelled ones |
| `create_task` | Créer une tâche | write | a *draft* task, with its description, project, type, priority and goal (by name, whatever the case, or id) — through the console's *New ticket*, so the same rules as any other; a person sets it *ready* in the console |
| `answer_question` | Répondre à une tâche bloquée | write | an answer under a blocked task's question, as the console's discussion writes it; `ready: true` also moves it back to *ready* |
| `list_solutions` | Solutions d'une tâche en attente | read | why a blocked task stopped (its kind, its reason, what is done) or what a task in review delivered (sentence, pull request, checks, points to check), and the choices the console offers on a blocked ticket's discussion and its Decide tab |
| `apply_solution` | Appliquer une solution | write | one of those choices: the decision and its instruction in the task's discussion, then the move — *ready*, *validated* or *done* |
| `list_memories` | Mémoire | read | what Ponos remembers: facts with their type, scope, source and state (accepted, proposed, refused) |
| `list_skills` | Skills | read | the skills Ponos gives its sessions (name, description, scope, state, clashes) and, read only, those the repositories hold |
| `propose_memory` | Proposer un souvenir | write | a fact put to the person; it stays *proposed* — no session reads it — until accepted in Context → Memory |
| `list_library` | Bibliothèque | read | the reference files kept for the sessions: name, description, tags, scope, type, size and path on this machine — the content is read from the path |
| `get_library_file` | Un fichier de la bibliothèque | read | one file's metadata |
| `create_idea` | Proposer une idée | write | an idea among the proposed ones, to be kept or thrown away |
| `set_idea_state` | Garder ou jeter une idée | write | `keep` (for later, nothing on the board), `ticket` (a draft, as swiping right in the pile does), `discard`, or `new` to propose it again |

**Nothing else.** No tool runs a command, changes the settings or deletes anything. A task a
client creates is always a draft: a ready one runs a session with every right on this machine,
so it waits for a person to read its brief and set it *ready* in the console. Answering a
blocked task, or applying one of its solutions, does start its session again.
The descriptions the tools carry are in French, and say when to use each one.

**Two scopes, two keys.** `read` is every reading tool; `write` adds the ones that write — the
consent page leaves it unticked, tick it for a connector you trust to act. The page names the
client as it named itself, and the host the key is sent to, which the client cannot choose a
name for; a client never let in before is said to be new. A client given `read`
alone is not even shown the others, and a write it asks for anyway is refused. The console's
own token and its cookie are **not** keys to `/mcp`: they open everything behind that port,
and a connector is given less. Every write asked for — refused ones included — is written to
the local database with the tool, the time and the client: `ponos mcp list` shows the clients
and the last writes, `ponos mcp revoke <client>` takes back all of one client's keys at once, and
`ponos service run --sign-out-everywhere` those of every connector that came in over OAuth — the tokens
drawn with `ponos mcp token` stay, and it names them with the line that takes each back.

### How the connection works

The Leadz connector's road, step by step — OAuth 2.1, as the MCP specification names it. Any
request to `/mcp` without a key, a `GET` as a `POST`, is answered `401` with
`WWW-Authenticate: Bearer resource_metadata=…`; that document
(`/.well-known/oauth-protected-resource`, RFC 9728) names the authorisation server, whose own
(`/.well-known/oauth-authorization-server`, RFC 8414) gives the three addresses. The client
registers itself (`/oauth/register`, RFC 7591), sends you to `/oauth/authorize` — the page that
names it and asks for the console's password (or its token) unless the browser is signed in —
and exchanges the code with PKCE (`S256` only). The access token lasts an hour, the refresh
token ninety days and turns over at each use; each is kept as its SHA-256 only. A refresh token
that comes back after it turned over has been used by somebody else first: it takes every key of
its client with it, and the connector has to be connected again.

Registering is open, since a connector does it before anybody signs in, so it is counted: one
address registers twenty clients an hour, and the twenty-first is answered `429` with
`Retry-After`. The daily tidy forgets what ran out — a code or a token a day after it expired,
and a client registered over the network that holds no key any more (never authorised, or silent
past its ninety days) once it is a day old; such a connector registers again when it comes back.
The clients drawn with `ponos mcp token` are never purged.
