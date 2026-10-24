# The board

[The guide](README.md) · [Ponos](../README.md)

The board as Markdown files, and the Notion side: its databases, and what a ticket carries.

## Without Notion: the board as Markdown files

Notion is not required. The runner talks to a board through one interface
(`src/ponos/store.py`), and which board answers is one line. A fresh configuration
still says `notion`, because that is what every installation before this one ran on — a
default kept for them, not a requirement.

```toml
[storage]
mode = "markdown"          # "notion" (the default) · "markdown" · "both"
path = ""                  # empty: ~/.local/state/ponos/board
```

In `markdown` mode nothing reaches the network. There is no token to create, no page to
share, no integration to grant capabilities to; `ponos doctor` stops asking Notion
who you are, and `require_usable` stops asking you for a token. The board is a directory:

```
board/
  context.md                     who the work is for — read into every prompt
  tickets/<slug>-<id>.md
  projects/<slug>-<id>.md
  agents/<slug>-<id>.md
  schedules/<slug>-<id>.md
  goals/<slug>-<id>.md           what the tickets are for — see the goals database
  comments/<id>.md               one page's discussion, oldest first
  trash/<collection>/            what the console deleted: a project, a schedule, a goal
```

One file is one page. Properties go in a YAML frontmatter under the names your board
spells them with, the content goes under it as Markdown:

```markdown
---
id: 3de451680af4811586ecde68ff380c89
title: Corriger l'entête de la page d'accueil
created: 2026-09-14T09:00:00+00:00
edited: 2026-09-14T09:12:31.884210+00:00
Status: Ready
Priority: 75
Project:
  - a5f1c2b7e1f04c0e9c8d1b2a3f4e5d60
---

Le titre déborde sur deux lignes en dessous de 380px.
```

Six keys are the page's own — `id`, `title`, `created`, `edited`, and the page's `cover`
and `icon` — and everything else is a column. A picture is a file beside the page
(`cover: northwind-b05e7e3a.cover.webp`), a URL, or — for an icon — an emoji. The column *types* are not declared twice: they come from `provision.py`, which
is the same place the Notion databases are built from, so a property the runner learns to
read is one both boards read the same day. Moving a ticket to the ready column is changing
one word in one file, which is the whole point: `git`, `grep` and `$EDITOR` become the
board's interface, and the directory can live in a repository of its own.

The console works against it exactly as against Notion — the board, a ticket's page, its
discussion, the live steps. And it gained screens that make a Markdown-only
installation self-sufficient: **Projects** (every project this installation knows of, the
board's and the ones only `[projects]` names — each of them a form a click opens in a drawer over the list, and a page of its own),
headed by the **global context** (the standing text every ticket is told first, for all the
projects: folded to a few lines, opened by *See all*, editable in place rather than read-only;
the old `Context` address leads there)
and an editable **Schedules** — a row is turned off
from the list itself, its name opens the six columns it is written in and the context its
tickets are born with, in a window that says when the next ticket is born, and a new schedule
is created unticked unless its « Turn on right away » box is ticked. Every
field of the console that holds Markdown — that context, the standing one, a project's
brief, a new ticket — is a Notion-like editor rather than a text area.

**A project has a picture.** The cover of its page and its icon — Notion's own, the
banner and the emoji or image in front of the title — are the thumbnail in the list of
projects and the banner of the project's page; a project with neither gets its initial on
a colour of its own. *Change the image* uploads a file (shrunk to 1500 px, WebP, before it
leaves the browser), takes a pasted address, or an emoji for the icon, and sets it on the
Notion page — through Notion's File Upload API for a file, as it is for an address. What
is changed in Notion comes back at the next reading of the projects. A file Notion keeps is
behind a URL that expires within the hour, so the console never shows that URL: it keeps
a copy under `~/.local/state/ponos/images/`, fetched again when the page was
edited since or the picture is another one. A change Notion refuses — no network, no right
to update the page — is kept and shown as chosen, says why, and is sent again at the next
reading; changed on both sides in between, the newest wins and the page says which.

### Both, and what happens when they disagree

```toml
[storage]
mode = "both"
conflict = "newest"
on_every_pass = true
```

A pass reconciles before it reads the queue, and every write the run makes lands on both
sides at once — so a ticket claimed at 14:02 does not spend thirteen minutes reading
*Ready* in the files while a session works on it.

Three rules, and they are the ones worth arguing about.

- **The newest wins, and the loser is written down.** A page changed on both sides since
  the last reconciliation is a conflict; `conflict = "newest"` keeps the later
  `last_edited_time`, and the version that lost goes into the journal with both
  timestamps and the name of the side that won. Both are compared to the minute, the
  resolution Notion answers at; within the same minute Notion wins, and the journal says
  it was a tie. Nothing is overwritten quietly.
- **Nothing is deleted, ever.** A page that was on both sides and is now on one is
  journalled as a deletion and left exactly as it is on the side that still has it. A file
  disappears for a hundred reasons — a bad merge, a stray `rm`, an editor writing to the
  wrong place — and none of them is a decision to delete a ticket.
- **A timestamp to the minute is not trusted alone.** Notion keeps `last_edited_time` to
  the minute, so each stamp also carries a fingerprint of the page's properties: two
  edits in the same minute, with a reconciliation between them, are both carried.
- **A file is compared on what it says, not on its `edited`.** An editor leaves that line
  as it was, so each stamp also keeps a fingerprint of the file — its properties and its
  body: a ticket changed by hand reaches Notion on the next pass, and one changed by hand
  and in Notion is a conflict like any other, dated by the file's modification time.
- **A page that never existed on the other side is created there.** Which is what makes
  the switch work from a board that is already full: the first reconciliation copies
  everything across, in whichever direction it is missing. A page born in a file then
  takes Notion's identifier, because that is what its URL, its relations and every report
  about it will carry from then on.

The journal is the `sync_journal` table of `~/.local/state/ponos/ponos.db`, kept for
`log_retention_days`. The console and the runner write in it too, whatever the storage
mode: `seen` when the console notices a status change (with Notion's edit time — to the
minute, all Notion keeps — and the moment it saw it), `console→notion` when a move from
the console is confirmed, `write-failed` when one is given up on, `drift` when the
five-minute full read of the board finds something the incremental reads had wrong, and
`conflict` when a status was not written over somebody else's — by the console, or by a
run that finds its ticket moved by hand during the session:

```sh
ponos sync             # reconcile now, and say what moved
ponos sync --journal   # what past reconciliations did
```

---

## The Notion side

What it looks like from Notion, filmed on a demonstration board — the projects and
tickets are made up:

![A ticket in review, opened in Notion: the folded log of the run, then the comment with the pull request and the cost](../docs/media/notion/notion-read-result.gif)

*A ticket in review: the log Ponos folds into the page, then his comment — pull request, time, cost.*

![A writing ticket in Notion, the text Ponos wrote appearing in the page of the ticket](../docs/media/notion/notion-text.gif)

*A writing ticket: the text comes back in the page itself, ready to copy.*

![On the Notion board, a card dragged from In review to Validated](../docs/media/notion/notion-validate.gif)

*The go-ahead: drag the card to Validated, and he merges or publishes.*

### The tickets database

| Property | Type | Role |
| --- | --- | --- |
| `Name` | title | what the agent must do, in one line — leave it empty and the runner writes one from the body |
| `Status` | status *or* select | **what drives the whole system** — see [The statuses](tickets.md#the-statuses) |
| `Project` | relation | *optional* — to the projects database: decides the repository |
| `Agent` | relation | *optional* — to the agents database: decides who handles it |
| `Runner` | text | filled by the runner: which machine took the ticket |
| `Pull Request` | URL | filled by the runner at the end |
| `Session` | **URL** or text | written as soon as the ticket is claimed. Make it a URL and it becomes a link that opens the session; leave it text and it holds the bare ID |
| `Priority` | number | *optional* — a score from 0 (not important at all) to 100 (right now): the ready tickets run highest first, the oldest first on a tie; an empty cell is 50. A board whose column is still the old select of `Urgent`, `High`, `Normal`, `Low` keeps working — they read as 100, 75, 50 and 25, and a score is written back as the nearest word — until it is moved to a number column |
| `Model` | select | *optional* — `opus`, `sonnet`, `haiku`. This ticket's model, over its agent's and over `runner.model` |
| `Cost` | number | *optional* — written back, in dollars |
| `Duration` | number | *optional* — written back, in minutes |
| `Progress` | text | *optional* — **what the session is doing right now**, rewritten every ten seconds |
| `Scheduled` | date | *optional* — **hold the ticket until that moment**, then run it — or, on a validated ticket, publish it |
| `Waiting for credit` | checkbox | *optional* — ticked by the runner while the subscription's window is spent under the ticket. It does not move: it is still ready, and the tick is the note saying why nobody has got to it yet |
| `Type` | select | *optional* — `Code`, `Writing`, `External action`, `Publication`: **the road the ticket takes**. Empty, the runner works it out before running it — see [The type of a ticket](#the-type-of-a-ticket) |
| `Blocage` | select | *optional* — filled by the runner when a ticket stops: **why**, as a code (`merge.checks-failed`, `session.question`, `worktree.residue`…), emptied when it leaves *Blocked* or *Failed* — see [Why a ticket stopped](tickets.md#why-a-ticket-stopped) |
| `CI` | select | *optional* — written by the runner while the ticket is in *In review*: the state of its pull request's checks (`en cours`, `réussi`, `erreur`), empty for a repository without CI — see [CI on the card](tickets.md#ci-on-the-card) |
| `Sous-type` | select | *optional* — on a **Code** ticket, what kind of change it is: `Bug`, `Feature`, `Amélioration`, `Chore`, `Refactor`, `Perf`, `Docs`, `Sécurité`. Decides the prefix of its commit and pull request and its CHANGELOG section; ignored on the other types. Empty, the runner fills it — see [The sub-type of a code ticket](#the-sub-type-of-a-code-ticket) |
| `On` | text | *optional* — a **prompt Ponos runs at every change of the ticket's status**, yours or the runner's. Empty, nothing happens — see [A prompt on every change of status](tickets.md#a-prompt-on-every-change-of-status) |

`Waiting for credit` is an attribute rather than an eighth column, and on purpose: nothing
happened to a ticket nothing was started for, so nothing on the board should say it moved.
The pass that has credit again takes the ticked ones first — they are the ones already
half done — picks their session back up, and unticks them as it claims them. It is also
the reason this reaches a board you built last month: a property can be added to an
existing database through Notion's API, where an option on a real `status` cannot. Run
`ponos init` again and it appears; skip it and the runner waits out the credit
exactly as it did before, only silently. See [Stopping before the wall](credits.md#stopping-before-the-wall).

`Scheduled` is what turns the board into a calendar. A ticket without one starts within
seconds of reaching the ready column, so a date on it can only mean *not yet*: the runner
leaves it alone until the moment comes, then treats it like any other. Write the release
post on Monday, run the monthly report on the first — the ticket sits ready and waits.

The same date is honoured in *Validated*, which is where it pays off for work that is
already **finished**: the post is written, you have read it and said yes, and it still goes
out at the hour you chose. Accept it on Tuesday for Thursday 18:00 and it sits in its
column until Thursday 18:00 — no alarm to set, nothing to come back and click. Merges wait
the same way: one column, one rule.

A bare date means the start of that day in the runner's own timezone, so a ticket dated
30 August begins on the 30th rather than at some hour dictated by UTC. A date with a time
is taken as written, offset included. A range starts at its end — the moment the thing is
due. And a value the runner cannot read never holds a ticket back: a ticket is not frozen
by a date that failed to parse.

Precision is to the minute, and that limit is Notion's rather than the runner's: it stores
`14:48:27` as `14:48`. With a ten-second cadence a ticket therefore starts within a few
seconds of the minute you named, which is as close as the board can express.

The last six are optional in the strict sense: a database without them behaves exactly as
before, because the runner only ever writes properties the schema declares. Add them and
you get a queue you can steer — a cheap model for a documentation ticket, an expensive one
for a refactor — and a board that shows what each ticket cost.

The **body** of the ticket page is sent to the agent as the description. Write there what
you would tell a developer who does not know the subject: what must change, where, and
how you will know it is done.

And you may stop there. A ticket is often written the way the thought arrives — the
content first, the title never — so a ticket that reaches *Ready* without one is named by
the runner: a very short session reads the page and writes a title back **into Notion**,
in the language the page is written in, so the board shows it too. It happens before the
branch is drawn, which is what the title is first used for: `ticket/reparer-le-bandeau-…`
rather than one more `untitled-ticket`. A ticket that already carries a title keeps
exactly the one you gave it and costs nothing extra; a ticket with neither a title nor a
body is not invented for — it comes back with the question. And if the naming fails, for
want of a session or of a Notion that accepts the write, the ticket runs all the same,
under the label it had.

### The type of a ticket

A ticket used to be one of two things, and its project decided which: a repository meant a
pull request, no repository meant a text in the page. Tickets have since started asking
for things that are neither — *enter these DNS records at Hostinger*, *post this on
LinkedIn*, *deploy that* — and those do not take the same road, nor go wrong the same way.
A pull request is read before it is merged; a post, once it is out, is out.

So a ticket has a `Type`, and its four values are told apart by **how the work is carried
out**, not by what it is about:

| Type | The road | What comes back |
| --- | --- | --- |
| **Code** | a worktree, a branch, commits, a pull request — what every ticket on a repository always was | *In review* with its pull request |
| **Writing** | no repository: a scratch directory and `ANSWER.md`. On a project that has one, the session may *read* it, never change it | *Done*, the answer in the page |
| **External action** | no repository, the browser allowed (Claude in Chrome), a DNS zone, a service's settings, a deployment or a setting in production. **It stops at its first doubt** — a wrong account, a value the ticket does not give — rather than acting on a guess | *Done*, with the **log of every action** in the page: where, what changed, before and after, what was checked |
| **Publication** | public and irreversible: a post, a message sent. **In two steps** — see below | *In review*, nothing published; then *Done* once you validated it |

**Empty is a request.** A ticket that reaches *Ready* with no type is classified before
anything else happens to it: a short session on a light model (`runner.classify_model`,
`haiku` by default) reads its title, its content, what was said in its comments, and
whether its project has a repository — a project without one cannot be *Code*. It answers
in JSON: a type, one sentence saying why, a confidence (`low`, `medium`, `high`) and the
type it hesitated with. The runner writes the type into the column and the sentence into a
comment, then runs the ticket exactly as if you had picked that type yourself:

> **🏷️ Classified — Publication · high confidence**
> The ticket asks for a post on LinkedIn, which goes out in public.
> Wrong? Change the Type column — a type somebody chose is never overwritten.

It runs in the pass's own thread, like the session that names a nameless ticket: it starts
nothing beside the sessions in flight and holds none of their places for longer than it
takes to answer one question.

**A doubt is never settled by running the ticket.** Three answers stop it, and it goes to
*Blocked* with the question, the reason under it, and nothing executed:

- the classification said nothing usable — no session, no JSON, a type that is none of the
  four;
- it is less sure than `runner.classify_confidence` asks (`medium` by default, so `low`
  stops it);
- it hesitated between two types and one of them is *External action* or *Publication* —
  a text run as a text that was a publication is a post nobody read before it went out.

**Except between Code and another type: that one is settled, not asked.** An audit, a
check, a deployment or a setting changed in production reads like code because it is about
code — and run as code it came back blocked for want of a commit nobody had asked for. So a
classification that hesitates between *Code* and anything else takes the other type, whose
deliverable is its report, whatever its confidence, and the comment says so: *it could have
been Code: I took External action, which asks for no commit*. One click in the column puts
it back.

The comment asks *Writing or Publication?* and says which is the more careful of the two —
in doubt, always the one further along *Writing → Code → External action → Publication*.
**The Type column is left empty** rather than filled with that guess: a type the runner
wrote would read, on the next pass, as a type you had chosen. Pick it, answer in the
comment, and the ticket runs on the next pass — an answer that names the type is read by
the next classification too.

**A type somebody chose is never touched.** Not overwritten, not re-classified, not asked
about. An option that is none of the four — a column you use for something else — is left
alone as well, and the ticket runs by its project as it always did. A board without the
column at all, or `runner.classify = false`, is the runner exactly as it was; `ponos
init` adds the column to an existing board, and `ponos doctor` says which of the
four options it offers. A board spelled in French — *Rédaction*, *Action externe* — is read
as such without a word of configuration; `[notion.types]` renames them otherwise.

**A publication goes out only once you have said yes.** It is the two-step road, built on
the columns the board already has:

```
Ready        ──▶  classified Publication (or typed so by you)
In progress  ──▶  a session prepares it — the text, the visuals, the target, the moment —
                  and publishes nothing: no post, no send, no draft on the service
In review    ◀──  the content is in the page. You read it.
Validated    ──▶  you moved it: a second session publishes it, word for word
Done         ◀──  with where it went
```

The second step is the one [Validated](tickets.md#validated-and-what-it-sets-off) has always done for
a ticket with no pull request, and a publication takes it **whatever its project holds** —
a post about a repository's release is still prepared in its page and never in a branch. A
board without a *Validated* column has no such gesture: the prepared content lands in
*Review* (or *Done*) and publishing it is yours.

### The sub-type of a code ticket

A **Code** ticket also says what kind of change it is, in its `Sous-type` column — a select
with eight options, which `ponos init` adds and `ponos doctor` asks for:

| Sub-type | For | Commit / PR | CHANGELOG |
| --- | --- | --- | --- |
| 🐞 `Bug` | something does not work as it should | `fix:` | *Fixed* |
| ✨ `Feature` | a capability that did not exist | `feat:` | *Added* |
| ⬆️ `Amélioration` | making better what exists — UX, UI, wording, ergonomics | `feat:` | *Changed* |
| 🧹 `Chore` | upkeep: dependencies, CI, configuration, tooling, cleaning up | `chore:` | none, or *Maintenance* where the CHANGELOG has one |
| ♻️ `Refactor` | restructuring the code without changing what it does | `refactor:` | *Changed*, if anybody can tell |
| ⚡ `Perf` | performance | `perf:` | *Changed* |
| 📝 `Docs` | documentation, README, a documentation site | `docs:` | none |
| 🔒 `Sécurité` | a hole, a secret, permissions | `fix:` | *Security* |

It goes into the session's prompt, which is what makes a commit start with `fix:` and its
entry land under *Fixed*; the pull request the runner opens takes the same prefix, in place
of the tag in the title (`[Bug] The button…` becomes `fix: The button…`), so a squash merge
puts a conventional commit on the base. A **Bug** asks for one thing more: a test that
reproduces it, failing, before the fix. The column is ignored on the other types, and
English spellings (`Improvement`, `Security`) are read as well.

**Empty is a request**, as for the type, answered the cheap way first:

- **a prefix in the title says it**, without asking anybody: `[Bug]`, `[Feature]`,
  `[Amélioration]`, `[Perf]`, `[Docs]`, `[Refactor]`, `[Sécurité]`, and `[Ops]` for a
  *Chore* — wherever it sits (`Ponos — [Feature] …`), and the first one that is a sub-type
  (`[UX] [Bug] …` is a bug: `[UX]` is a domain, not a change);
- otherwise **the classification says it** — the same short session that tells a ticket's
  type, on the same light model, answers both at once; on a ticket whose type you wrote, a
  session of its own asks only the sub-type;
- **in doubt, it is an *Amélioration***, and the ticket's report says the runner was not
  sure. Not a question: a wrong sub-type costs a word in a commit, not a post published.

The runner writes what it chose into the column, and **never rewrites a value that is
there** — yours, or its own from an earlier attempt. A board without the column reads the
prefix alone and asks no session, having nowhere to keep the answer.

**The tickets already on the board** are filled once, from their prefix and nothing else:

```sh
ponos subtypes                       # the code tickets, by sub-type
ponos subtypes --backfill --dry-run  # what a prefix would fill
ponos subtypes --backfill            # fill them
ponos subtypes --backfill --all      # the done and cancelled ones too
```

Never a session: a guess is not a fact about the past, and a ticket without a sub-type
prefix stays empty. Done and cancelled tickets are left alone unless `--all` says so,
because writing on one is editing it, and a done ticket the runner did not close itself
is dated by its last edit in the statistics: a year of closings would all land today. The
console does not need them written — a code ticket with an empty column is read by its
prefix, so the old ones wear their badge and are counted all the same.

On the console, a code ticket wears a small badge of its sub-type — its icon, in its colour
—, the search bar filters by it, *New ticket* offers it, and the statistics count the code
tickets closed by sub-type and by week, with what one of each cost and lasted on average.

### The model of a ticket

A ticket with no `Model` used to run on `runner.model` — in practice the heaviest model
there is, for *remove that paragraph* as much as for *audit the whole repository*. **Empty
is a request here too**: with `runner.auto_model` (on by default) the runner picks the
model itself, before the session starts. A `Model` on the ticket, or on its agent, is
always taken as written.

Not by asking a model: a few rules read off the ticket cost nothing, give the same answer
twice, and say exactly why. Four levels, each answered by a model of the configuration —
`haiku`, `sonnet`, `opus`, `fable` by default (`runner.auto_model_light` …
`auto_model_heaviest`):

- **the type** sets where it starts (`runner.auto_model_code` and the three others):
  *standard* for Code, External action and Publication, *light* for Writing — a board
  without types starts a ticket on a repository at *standard*, any other at *light*;
- **the sub-type** of a code ticket moves that start: *Docs* and *Chore* one level lower,
  *Sécurité* one level higher, the others where Code starts (`runner.auto_model_subtype_docs`
  and the seven others: `lower`, `same` or `higher`, also in the Settings' model table) —
  never past the lightest or the heaviest level, and Fable still only when it is allowed;
- **the size** moves it: one of ordinary size is at least *standard*, and a long one
  (600 words, or 25 list items) goes up a level;
- **a small change drops to *light***: one that only asks to remove, rename or reword
  something — a text, a label, a colour — said in its title (up to 250 words and 10 list
  items around it), or anywhere in a short request (120 words, 5 items);
- **the words** that announce heavy work — *audit*, *architecture*, *migration*,
  *refonte*/*refactor*, *débogage*/*debug*, *diagnostiquer*, *sécurité*, *performance*,
  *multi-dépôts* —
  take it to *heavy*, and to *heaviest* when the request is long and names two of them;
- **the priority**: a ticket scored 75 or more never runs on the lightest model.

External action and Publication never drop below where their type puts them: a browser
driven by the lightest model clicks the wrong button. The choice and its reason go into a
comment, not into the `Model` column — written there, it would read on the next attempt
as a model somebody chose:

> **🧠 Model chosen automatically — haiku**
> Code ticket, small targeted change (retirer).

**A run that failed goes up one level, once.** A ticket whose chosen model ended in
*Failed* — a crash, a timeout, a session going round in circles — runs one level higher
when it comes back, and its comment says so (`runner.auto_model_escalate`). Once: the next
attempt keeps that model rather than climbing to the top of the price list. A ticket
stopped by the quota carries its session on with the model it began on. What a run was
chosen and how it ended is kept in the local journal, so this works the same on a Notion
board, a Markdown one, or both. Through OpenRouter, name its slugs in the four levels.

**Fable only when you say so.** It costs far more than Opus, so `runner.use_fable` is
off by default, and then nothing the runner starts runs on it: the *heaviest* level, and
any level whose model is `fable`, runs on `opus`, an escalation stops there, a session
begun on Fable carries on on Opus, and a `Model` of `fable` written on a ticket or its
agent runs on Opus too — its report says *Fable is turned off in the settings: run on
Opus.* The console's chat, the naming and classifying sessions and the conflict
resolution follow the same rule. Turn it on to get the behaviour above unchanged.

### Following the work

#### Live, on the ticket itself

A run used to say nothing between *In progress* and the pull request. Now it narrates:
while the session works, its steps are written **into the ticket**, on a ten-second
cadence.

Two places, and they answer two different questions.

- **The page** gets one toggle per run — `⏳ Live — 12 steps · 3 minutes` — and under it
  what the agent *said*, one paragraph after the other, whole and in its own markdown.
  The commands, file reads and edits are counted in the title but never written: their
  detail is in the run journal the console reads (see [The run journal](troubleshooting.md#the-run-journal)) and in
  the log (`ponos logs -f`). Open it to follow the
  work; leave it collapsed and its title alone tells you it is moving. When the
  run ends the toggle settles into `✓ 27 steps · 6 minutes · removed the header`, and
  stays as the story of what happened — or into `⚠️ Trace — 27 steps · 6 minutes`, with the
  command that resumes the session and the path of its log inside, on a run that did not
  get there. Its title follows `runner.language` like everything else the runner says.
- **The `Progress` column** carries the last line, so a glance at the board — from a
  phone, without opening anything — shows which ticket is on `Bash · npm test` and which
  is still reading. It is cleared when the run ends: the comment, the status and the pull
  request speak from then on.

What the agent *said* is shown as it said it, on the page, in that column and on the
console's card under *Ponos is working…*: the run does not rewrite it into a step of its
own. So it is the prompt that sees to its language — with `runner.language` set, the
sentence that asks for the report in that language asks for these lines too, as short,
whole sentences rather than notes the agent leaves itself (“Now delivery around the
claim.”). Without it, the agent keeps its own habits, which are often English.

```
⏳ Live — 12 steps · 3 minutes
   I will remove the banner from the template and the stylesheet rules that
   went with it, then run the tests.

   The banner is gone and the tests pass. I stop my server and run the full
   checks.
```

A **cadence, not a stream**: a session emits several events a second, and writing each one
would rewrite the page continuously, spend the integration's rate limit and produce
something nobody can read. Ten seconds is the default, five the floor:

```toml
[runner]
progress = true
progress_interval_seconds = 10
```

What reaches the ticket is what the agent *says* — the part a human reads — and nothing
else: no line per command, file read or edit, and no failed tool call either, since the
agent's next sentence says what it made of it. It is not shortened: it goes down entire,
and only a turn of several thousand characters is ever cut. A session that talks past
three hundred paragraphs stops there, with a line saying so: a ticket page is not a log
file. And a board with no `Progress` column, or an integration
that refuses the write, costs the report and nothing else — the ticket runs to its end
either way.

The toggles are the page's, not the brief's. A ticket sent back to *Ready* is briefed on
what you wrote and on the report each run ended on — the pull request, the answer — but
never on the toggles: the next session does not pay for the steps of the last one, nor
take them for instructions, and the console's view of a ticket leaves them out as well.
They are recognised by their title, so a toggle of your own is still read. On a Markdown
board, which has no toggle, the story of a run is written between `<!-- ponos:live -->`
and `<!-- /ponos:live -->` and left out the same way.

`ponos init` adds the column to an existing board; the toggles need nothing.

#### From the terminal

`Session` is filled **when the ticket is claimed**, not when it finishes — so a ticket
sitting in *In progress* is exactly the one you can look into:

```sh
claude --resume <session id>          # reopen the conversation, read it, carry on
ponos logs -f                 # the live feed of the running session
ponos logs <ticket id>        # a past session, rendered
ponos logs <ticket id> --raw  # the raw JSON stream
ponos logs <ticket id> --runs # every run of that ticket, from the run journal
ponos logs --runs             # the latest runs, every ticket
ponos logs --service [-f]     # the runner's and the console's own journal, ponos.log
```

`ponos logs <ticket id>` finds the ticket's newest run in the journal, so a session that
was started over — and wrote a second log — is found too; tickets that ran before the
journal are found by their log's name, as they always were.

**Make `Session` a URL property and its cell becomes a button.** Clicking it opens a
terminal already inside that conversation — no identifier to copy, no directory to find.
`install.sh` registers a `ponos://` scheme with your desktop for exactly this, and
`ponos open <link>` is what runs behind the click. Which of the two you get is
decided by the column's type in Notion, nothing to configure: a URL column gets the link,
a text column gets the identifier.

The terminal is picked from the usual suspects — GNOME Terminal, Konsole, xfce4-terminal,
kitty, Alacritty, foot — or set `PONOS_TERMINAL` to yours.

Every ticket is a **real Claude Code session** — not a private log format, the same
transcript your own sessions produce. `claude --resume` works from any directory, and
keeps working after the worktree is gone: the transcript lives in `~/.claude/projects/`,
not in the checkout.

By default they also **show up in the project's session picker**. A session started
inside a disposable worktree would otherwise be filed under that worktree, so opening
`claude` in the repository would never list it; when a ticket finishes, the runner moves
its transcript under the repository's own directory instead. Open `claude` in the repo,
pick the session, and you are inside the conversation that produced the pull request.
Tickets with no repository are filed under `workspace_root`. Set
`attach_sessions = false` to leave them where they ran.

This one reaches into Claude Code's own storage layout, so it is written to fail quietly:
if the layout ever changes, the move is skipped and the session stays resumable by its
identifier, exactly as before.

While a session runs, its worktree is also a normal repository —
`git -C ~/.local/state/ponos/worktrees/<name> diff` shows you what it has changed
so far.

The runner also posts a comment on the ticket when it finishes. Notion pushes that
comment to your phone as it stands, so it *is* the notification, and it is written as one:
a verdict saying what is expected of you, the figures that place it, one sentence and the
link — three lines, and never the machinery. That one needs a capability the
integration does not get by default: **notion.so/my-integrations → your integration →
Capabilities → Insert comments**. Without it the run still succeeds, and the log says the
comment was refused with a 403.

#### The language it answers in

That comment is the runner talking, and `runner.language` is what decides which language
it talks in. `"fr"` — or `"FR"`, or `"fr-FR"`, or `"français"` — and every report, every
question a blocked ticket asks, every line that reaches your phone comes back in French:

```
✅ À relire — PR #12 · 3 commits · 18 minutes · 1,20 $
Le header du tableau de bord a été retiré, les tests passent.
https://github.com/you/site/pull/12
```

Where the rest went: the machine that ran it is the board's *Runner* column, the session
is its *Session* column — a link you click rather than a command you copy — and the
command that resumes it, with the log path, is folded into the block the run writes its
steps into, on the days a run went wrong. On the other days nobody has ever needed them.

The same line also travels into every prompt, so the summary at the top of a report, the
document a ticket with no repository produces, the answers given in the comments and the
sentences the session says while it works — the `Progress` column, the live block — are
written in it too. What it does *not* touch is the repository: commit messages, code and
identifiers keep the language the repository already uses, because a branch is read by
whoever works on it and not by whoever asked for it.

**Empty — the default — is English, and it is more than that: it means nobody decided.**
Each session then keeps the rule its prompt already carries — answer in the language the
ticket is written in, reply in the language you were written to — so a ticket written in
French comes back in French, under a report written in English. That is the runner as it
has always behaved, and naming a language here is what replaces it with a decision.

Everything the runner writes where you read it follows the setting: the comments under a
ticket, the title of the folded block (`✓ 130 étapes · 19 minutes`), the line that resumes
the session, the body of the pull requests it opens, the note about a branch a ticket
already had, the line a ticket born of a schedule opens with, the answer it relays from
Telegram or Slack, and the desktop and phone notifications. Only an error is quoted as it
came — git's, GitHub's, Notion's — because it is evidence, not a sentence. The journal on
the terminal and the CLI stay in English: they are read by whoever is standing at the
machine.

An answer is understood whatever language it is typed in: *oui*, *ouais*, *vas-y* and
*yes*, *ok*, *go* are all a yes; *non*, *laisse tomber* and *no*, *stop* all a no — on a
board told to answer in either.

**The console has a language of its own, `runner.app_language`**, and by default it is the
same one: `language = "fr"` alone is enough to have the console open in French too. Set
`app_language` to have the two apart — tickets answered in English, a console in French, or
the reverse. Both empty, the console reads the browser's languages, as it always did. It is
only where the console *opens*: the FR / EN select in its header still switches it, and the
choice made there is kept by the browser and wins over the file. The sign-in and first
set-up pages follow the same setting.

Two languages are spelled out today, `en` and `fr`; a third is a column in
`voice.py` — every phrase in one table, and `tests/run.py` fails if a phrase is missing
in one of them.

### The projects database

One row per project, and **the project decides what kind of work its tickets are.**

A project that names a repository is a **code project**. Its tickets get a git worktree, a
branch, commits and a pull request. Three ways to name it, most explicit first:

1. a `[projects]` entry in your configuration — `"Trader Ia" = "~/workspace/labo/trader-ia"`;
2. a **`Path` property on the project page**, which keeps the mapping on the board rather
   than in a file on one machine;
3. a **`Repository` property** — a GitHub URL or `owner/name` — matched against the
   `origin` remotes of every repository found under `workspace_root`. A repository
   renamed on GitHub is still found under its old name: `gh` is asked what it is called
   now, and that name is matched instead.

Both columns are read by name, whatever their capitalisation, and the `github` column
earlier versions asked for still works.

A way that fails gives way to the next: a `Path` pointing at a folder that was renamed
does not stop the `Repository` property from finding the clone. The ticket runs, and its
comment says which declaration is out of date — `ponos projects` shows the same
project with a `!` rather than a tick until you correct it. What a later way may find is
bounded, though: a repository is only ever taken on the strength of its `origin` remote,
never because its folder is named like the project, and never when two clones answer to
the same remote. A project none of its declarations lead to is put back, with every way
that was tried and why it failed in a comment.

**A repository you have never cloned is cloned, not refused.** Creating a project with
its GitHub link and nothing else is enough: the first ticket that needs it runs
`gh repo clone` — or `git clone` on a machine with no `gh` — into `workspace_root`, under
the repository's own name, and works in it as if it had always been there. Its comment
says where it came from. That only ever happens for the run that is about to work on a
ticket: `ponos projects`, `ponos next` and a dry run download nothing,
and nothing is cloned twice — every way of matching a clone you already have is tried
first, and a remote two clones already answer to is still a question rather than a third
copy.

**A project can be created from the console.** *New project*, beside *cards / table* on the
Projects page or in Ctrl+K, opens a window drawn like *New idea*: the name, a line saying
what the project does, *Code* or *Writing*, then — for code — its repository either on
GitHub (`owner/repo` or any github.com address, kept as `https://github.com/owner/repo`) or
as a folder of this machine, whose `origin` fills the GitHub field in; its public address;
and the brief, which becomes the body of the page. While it is typed, the console says
whether that repository is already cloned here or will be at the first ticket. Ctrl+Enter
creates it, through the same store as everything else — a Notion page, or a file on a
Markdown board — in the columns the projects database already has (`github` rather than a
second `Repository` beside it; `Description` and `URL` where the database has them). A
name the workspace already has, in any case, an address that is not GitHub's, and a folder
that is not a git repository here are refused under their field, in `runner.language`. The
new card comes first in the list, marked, its *+ Ticket* ready — or, with *Create a first
ticket* ticked, the ticket's form opens straight away with the project in it.

A project that names none — and **a ticket with no project at all** — is **document work**.
It gets a disposable scratch directory instead of a worktree, and the agent's answer is
written back into the Notion ticket as real blocks: headings, lists, checkboxes, links.
No branch, no pull request. That is what you want for *"draft me the steps to become a
certified trainer"* or *"summarise this for me"*: there is nothing to commit, and the
deliverable is the page itself.

**Whatever you write on the project page becomes standing instructions** for every
ticket of that project. Not the ticket's page — the *project's*. It is prepended to the
brief the agent receives, so it is written once instead of retyped into every ticket:

> **Communication**
> Tone: first person, short sentences, no superlatives. No emoji, no hashtags. Show a
> verifiable number, not a promise. If the tool has a limit, say it.
> X: 280 characters for a single post. Always offer two or three angles.

That is what turns *"write me a post about the new tool"* into your voice rather than a
generic one — and, on a code project, what carries conventions that do not belong in any
single ticket. An empty project page costs nothing and changes nothing.

The runner never guesses from a project's name. A name that happens to match a folder is
a coincidence, and turning a writing task into commits on a like-named repository is a
worse outcome than asking you to be explicit. But a repository that *is* named and does
not exist is an error, and blocks the ticket rather than silently falling back.

`ponos projects` shows you which is which for every referenced project — worth
running once after installation; it is what saves you from surprises.

### The context page — who the work is for

One row of the workspace, named `Context` by default, is a plain page with no database in it.
Whatever you write there goes into **every prompt, on every project**, ahead of the
project's brief:

```
the context page   who you are, what you work with, how you like things written
      ↓
the project page   the conventions of THIS project
      ↓
the ticket         the task
```

From the widest frame to the narrowest, so the specific is read last and wins when the two
disagree. What belongs there:

> Je suis <prénom>, développeur web depuis 13 ans. Je travaille sur une boutique en ligne.
> Stack: PHP/Symfony, React, Docker. `pnpm`, jamais `npm`.
> Réponses courtes, pas d'emoji, la commande plutôt que l'explication.

It pays for itself mostly on **document tickets**: there the agent starts in an empty
directory and knows nothing about you at all, whereas on a code ticket the repository and
its `CLAUDE.md` already answer most of it.

Two things to keep in mind. **Keep it to one screen** — it is the one text billed on 100 %
of your tickets, and a long preamble dilutes the ticket itself. And what belongs to a
single project belongs on that project's page, not here: the test is whether it would
change the answer on a ticket of *any* project.

The page is optional. Without it the runner behaves exactly as before, and says so once
per run rather than leaving you to wonder.

### The agents database — who handles the ticket

A project says *where* the work happens. It says nothing about **who** does it, and
“fix this regression” and “write this announcement” are not the same craft on the same
repository.

Add an `Agent` relation column on your tickets, pointing at a database of agents. One row
per role, and **the body of its page is the role**, exactly as a project page is its brief:

> **Dev front**
> Tu touches au CSS avant le JS. Aucune dépendance nouvelle sans raison écrite.
> Un test qui reproduit le bug avant le correctif.

An agent row may also carry a `Model`, which is how a rewriting ticket runs on a cheaper
model than a refactor. The narrowest choice wins:

```
the ticket's Model  →  its agent's Model  →  the model chosen for it  →  runner.model
```

The third only with `runner.auto_model` on — see [The model of a ticket](#the-model-of-a-ticket).

The role is read after your context page and after the project's brief, and **it can never
loosen the frame**: committing without pushing, and answering `RESULT: blocked` rather than
guessing, live in the template, above anything a page can say.

All of it is optional twice over: a tickets database with no `Agent` column behaves exactly
as it always has, and a ticket that names no agent runs on the runner's own prompt.

### The goals database — what the ticket is for

A project says *where*, an agent says *who*. Neither says **what for**, and “add a column”
is not the same task a month before a launch as on a cleanup nobody is waiting on.

One more row of the workspace, named `Objectifs` by default, holds a database of goals.
Add an `Objectif` relation column on your tickets, pointing at it. One row per goal, and
**the body of its page is the goal's brief**, exactly as a project page is its brief; two
columns of the row say what a session cannot guess:

> **Lancer la v1** — Critère : dix clients payants · Échéance : 31/12
> La version que l'on montre. Tout ce qui ne la rapproche pas attend.

A ticket that points at one carries it into its prompt, under `# L'objectif — <name>`, with
its criterion and its due date. Only the first goal of the relation is read. Its place is
fixed:

```
the context page   who you are
      ↓
the project page   where the work happens
      ↓
the goal           what it is for
      ↓
the agent          what craft it takes, and its rules — read last
```

The goal is the intent of the task, not a rule: the role's rules stay the last thing read.
A prompt file of your own written before `{goal}` existed still gets the goal, at its end.
The queue does not read it — a goal's `Priorité` does not order the tickets. What else reads
the goals is the console's [Goals](console.md#goals) page, the [ideas](console.md#ideas) (the active goals of the
scope, under « Les caps du moment ») and the MCP connector's `list_goals` and `create_task`.
On a board of Markdown files the database is the `goals/` directory, with the same columns.

All of it is optional twice over: a tickets database with no `Objectif` column, an empty
relation or a goal page the integration cannot read all give the prompt you had before, to
the character. A workspace without the `Objectifs` row says so once per run, and runs.
