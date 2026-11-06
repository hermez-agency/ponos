# The board

[The guide](README.md) · [Ponos](../README.md)

Where the tickets live, with Notion or without it, and the Notion side: its databases, and what a ticket carries.

## Without Notion

Notion is not required. The tickets live in `ponos.db` (`~/.local/state/ponos/ponos.db`),
whatever the installation: the runner, the console, the MCP and the CLI read and write them
there. What Notion adds is a second place to see them and to write them from — see
[The mirror](#the-mirror-ponosdb-first-notion-a-copy).

The other objects of the board — the projects, the agents, the goals, the schedules and the
standing context — live in Notion when `notion.token` is set, and in the `board_pages` table of
the same `ponos.db` when it is not. So an installation with no token is a valid one, with
nothing to configure: no token to create, no page to share, no integration to grant
capabilities to. `ponos doctor` stops asking Notion who you are, and `require_usable` stops
asking you for a token. `install.sh` and the Docker image do not ask for one either, and the
console's first connection offers both roads on its Notion step: connect a Notion workspace, or
go on without. Giving a token later changes nothing about the tickets; the projects and the rest
are then read from Notion, which is where `ponos import notion` brings the tickets across.

The console works the same way in both cases — the board, a ticket's page, its discussion, the
live steps. And it has the screens that make an installation without Notion self-sufficient:
**Projects** (every project this installation knows of, the board's and the ones only
`[projects]` names — each of them a form a click opens in a drawer over the list, and a page of
its own), headed by the **global context** (the standing text every ticket is told first, for
all the projects: folded to a few lines, opened by *See all*, editable in place rather than
read-only; the old `Context` address leads there) and an editable **Schedules** — a row is
turned off from the list itself, its name opens the six columns it is written in and the
context its tickets are born with, in a window that says when the next ticket is born, and a new
schedule is created unticked unless its « Turn on right away » box is ticked. Every field of the
console that holds Markdown — that context, the standing one, a project's brief, a new ticket —
is a Notion-like editor rather than a text area.

**A project has a picture.** The cover of its page and its icon — Notion's own, the
banner and the emoji or image in front of the title — are the thumbnail in the list of
projects and the banner of the project's page; a project with neither gets its initial on
a colour of its own. *Change the image* uploads a file (shrunk to 1500 px, WebP, before it
leaves the browser), takes a pasted address, or an emoji for the icon. With Notion, it is set
on the Notion page — through Notion's File Upload API for a file, as it is for an address;
without, it is kept in `ponos.db`. What is changed in Notion comes back at the next reading of
the projects. A file Notion keeps is
behind a URL that expires within the hour, so the console never shows that URL: it keeps
a copy under `~/.local/state/ponos/images/`, fetched again when the page was
edited since or the picture is another one. A change Notion refuses — no network, no right
to update the page — is kept and shown as chosen, says why, and is sent again at the next
reading; changed on both sides in between, the newest wins and the page says which.

The journal is the `sync_journal` table of `ponos.db`, kept for `log_retention_days`. The
console and the runner write in it: `seen` when the console notices a status change (with
Notion's edit time — to the minute, all Notion keeps — and the moment it saw it),
`console→notion` when a move from the console is confirmed, `write-failed` when one is given
up on, `drift` when the five-minute full read of the board finds something the incremental
reads had wrong, and `conflict` when a status was not written over somebody else's — by the
console, or by a run that finds its ticket moved by hand during the session. The console
shows it where it refuses a write.

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

### The mirror: `ponos.db` first, Notion a copy

Tickets are moving into `ponos.db`, and Notion is becoming a mirror of them. This
is the third of four steps: once `ponos import notion` has filled the database, the
runner, the console, the MCP and the CLI read and write the tickets there and never
ask Notion for one. Notion is touched only by the mirror below — projects, agents,
goals and the standing context are still read from it until you have let go of Notion (below).

**`ponos import notion`** brings home everything Notion still holds, in one run
you can replay: the projects, agents, goals and recurrences (under their own
identifiers, so every relation still lands), the standing context, and every
ticket — done and cancelled ones included — with its properties, its Mission and
its « What was done », the tickets it comes after, and its comments. The images
and files a page names are downloaded beside `ponos.db` (`page-files/`) and shown
by the console as before. Run it again and it adds nothing: what is already there
is left as it is, and only what is missing is completed. Until you have run it,
the tickets are Notion's as before; from the first ticket in the database on, they
are the database's. Notion itself is only ever read — never changed, never emptied.

**`ponos import notion --check`** is the parity report: it writes nothing, counts
both sides type by type (tickets, ticket texts, comments, « after » links, files,
and each kind of page), and lists whatever Notion has that `ponos.db` lacks. No
line in the list means nothing would be lost by letting go of the Notion token.
A ticket whose two parts are both written in `ponos.db` cannot lose a text, so its
page is not read again — only its comments are; the report says how many were spared.

**Letting go of Notion.** Once the report is clean, remove `PONOS_NOTION_TOKEN`
from `secrets.env` (keep a copy beside it) and restart the runner and the console.
With no token, Ponos has no mirror: projects, agents, goals, recurrences and the
context are `ponos.db`'s, every address Ponos writes for a ticket — notifications,
the pull request's body, `ponos list`, the reports — is the console's
(`/tickets/<id>`; the old page identifiers still name the ticket), and the Notion
workspace stays as it was, a read-only archive.

**A document or an external ticket delivers into `ponos.db`.** Its result is the
ticket's document (the « What was done » part), shown on the ticket's page in the
console, where *Edit* lets you correct it. The next session of the ticket writes
that part again from its own report.

**What still comes up from Notion** while a token is set is a closed list, read at every look of the daemon's upkeep (`interval_seconds`):

- a page you create;
- a change of status;
- a change to the Mission.

A comment written in Notion is no longer read: answer from the console, the MCP,
Telegram or Slack.

Everything else on the page — the pull request, the cost, the progress, the
priority, the model… — belongs to Ponos. If you edit one of those cells in Notion,
the mirror writes the database's value over it.

**The mirror** is the other direction: every change made to a ticket in
`ponos.db` waits in a queue, and each round of the daemon's upkeep sends it to Notion, in order. A change
that Notion does not take (a token that is no longer valid, no network) stays in
the queue with its count of tries and its last error, and goes again on the next
round; no ticket waits for it. A ticket whose changes are still queued is not read
from Notion until they have been sent, so the older word never wins over the newer.

**Notion can be down and the tickets still run.** A token that is refused, no network:
ready tickets are claimed, worked, delivered and answered from `ponos.db`, and the
mirror catches Notion up when it answers again. A daemon that cannot reach Notion starts
from the databases and the project pages it last read there (kept beside `ponos.db`);
a project page it never read cannot be found without Notion. A ticket created in the
console appears in Notion at the next round, and one created in Notion appears in the
console at the next, from either side.

### The tickets database

The names below are **fixed**: they are not settings, `ponos init` creates them exactly so,
and `ponos doctor` names each column a board lacks or holds under another type, each status
it does not offer and each option of `Sous-type` that is none of the runner's. A
configuration that still holds `[notion.properties]`, `[notion.status]` or `[notion.types]`
— they were how a board built by hand used to keep its own words — is read without them.

The options of the selects are **French** wherever they are words — `Rédaction`, `Action
externe`, `Amélioration`, `Sécurité`, `en cours`, `réussi`, `erreur`: it is the language the
board is written in, the one its tickets are typed in, and the one most of its options already
spoke. The development words a commit and a CHANGELOG share (`Bug`, `Feature`, `Refactor`…)
stay as conventional commits say them, and the statuses are the board's short lowercase
keywords (`ready`, `progress`, `review`…) its formulas and views filter on.

| Property | Type | Role |
| --- | --- | --- |
| `Name` | title | what the agent must do, in one line — leave it empty and the runner writes one from the body |
| `statut` | select (*or* status) | **what drives the whole system** — see [The statuses](tickets.md#the-statuses) |
| `Project` | relation | *optional* — to the projects database: decides the repository |
| `Rôle` | relation | *optional* — to the agents database: decides who handles it |
| `Agent` | text | filled by the runner: which machine took the ticket |
| `Pull Request` | URL | filled by the runner at the end |
| `Session` | **URL** or text | written as soon as the ticket is claimed. Make it a URL and it becomes a link that opens the session; leave it text and it holds the bare ID |
| `Priorité` | number | *optional* — a score from 0 (not important at all) to 100 (right now): the ready tickets run highest first, the oldest first on a tie; an empty cell is 50 |
| `Model` | select | *optional* — `opus`, `sonnet`, `haiku`, `fable`. This ticket's model, over its agent's and over `runner.model` |
| `Cost` | number | *optional* — written back, in dollars |
| `Duration` | number | *optional* — written back, in minutes |
| `Progress` | text | *optional* — **what the session is doing right now**, rewritten every ten seconds |
| `Scheduled` | date | *optional* — **hold the ticket until that moment**, then run it — or, on a validated ticket, publish it |
| `Waiting for credit` | checkbox | *optional* — ticked by the runner while the subscription's window is spent under the ticket. It does not move: it is still ready, and the tick is the note saying why nobody has got to it yet |
| `Plan d'abord` | checkbox | *optional* — on a **Code** ticket, **a plan before any code**: the first session only plans, and the work waits for your yes. Unticked by the runner once the plan is approved — see [Plan first](tickets.md#plan-first-a-plan-and-a-yes-before-any-code) |
| `Type` | select | *optional* — `Code`, `Rédaction`, `Action externe`, `Publication`, `Diagnostic`: **the road the ticket takes**. Empty, the runner works it out before running it — see [The type of a ticket](#the-type-of-a-ticket) |
| `Blocage` | select | *optional* — filled by the runner when a ticket stops: **why**, as a code (`merge.checks-failed`, `session.question`, `worktree.residue`…), emptied when it leaves *blocked* — see [Why a ticket stopped](tickets.md#why-a-ticket-stopped) |
| `CI` | select | *optional* — written by the runner while the ticket is in *In review*: the state of its pull request's checks (`en cours`, `réussi`, `erreur`), empty for a repository without CI — see [CI on the card](tickets.md#ci-on-the-card) |
| `Sous-type` | select | *optional* — on a **Code** ticket, what kind of change it is: `Bug`, `Feature`, `Amélioration`, `Chore`, `Refactor`, `Perf`, `Docs`, `Sécurité`. Decides the prefix of its commit and pull request and its CHANGELOG section; ignored on the other types. Empty, the runner fills it — see [The sub-type of a code ticket](#the-sub-type-of-a-code-ticket) |
| `On` | text | *optional* — a **prompt Ponos runs at every change of the ticket's status**, yours or the runner's. Empty, nothing happens — see [A prompt on every change of status](tickets.md#a-prompt-on-every-change-of-status) |

`Waiting for credit` is an attribute rather than an eighth column, and on purpose: nothing
happened to a ticket nothing was started for, so nothing on the board should say it moved.
Once the credit is back, the daemon takes the ticked ones first — they are the ones already
half done — picks their session back up, and unticks them as it claims them. It is also
the reason this reaches a board you built last month: a property can be added to an
existing database through Notion's API, where an option on a real `status` cannot. Run
`ponos init` again and it appears; skip it and the runner waits out the credit
exactly as it did before, only silently. See [Stopping before the wall](credits.md#stopping-before-the-wall).

`Plan d'abord` is an attribute for the same reason: a ticket planned first runs, asks and
is answered like any other, and only what its first session may do changes. `ponos init`
adds it to a board built before it, and the console's *New ticket* draws the box wherever
the board has it. The tickets of `ponos.db` carry it too.

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

So a ticket has a `Type`, and its five values are told apart by **how the work is carried
out**, not by what it is about:

| Type | The road | What comes back |
| --- | --- | --- |
| **Code** | a worktree, a branch, commits, a pull request — what every ticket on a repository always was | *In review* with its pull request |
| **Writing** | no repository: a scratch directory and `ANSWER.md`. On a project that has one, the session may *read* it, never change it | *Done*, the answer in the page |
| **External action** | no repository, the browser allowed ([Ponos's own](configuration.md#ponoss-browser-external-tickets-that-sign-in-on-their-own), or Claude in Chrome), a DNS zone, a service's settings, a deployment or a setting in production. **It stops at its first doubt** — a wrong account, a value the ticket does not give — rather than acting on a guess | *Done*, with the **log of every action** in the page: where, what changed, before and after, what was checked |
| **Publication** | public and irreversible: a post, a message sent. **In two steps** — see below | *In review*, nothing published; then *Done* once you validated it |
| **Diagnostic** | « X does not work »: an investigation, **read only** — the repository, its pull requests, Ponos's logs and what its project declares — see [A diagnostic](#a-diagnostic-the-cause-then-the-tickets-that-fix-it) | *Done*, the cause and its proof in the page, and the **fix tickets it wrote** on the board; *Blocked* with a question when no cause is found |

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

It runs in the daemon's own thread, like the session that names a nameless ticket: it starts
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

**A Code ticket that commits nothing is not always blocked for it.** Its worktree clean, the
session's report decides: work done outside the repository (Dokploy, DNS, Notion, the
Search Console…) and no word of a code change, it is *Done* with its report in the page; a
verdict that names what made the change needless — *nothing to change*, *already fixed on
main by #63*, a commit or a merged pull request — or the other pull requests it rebased,
fixed and merged, it goes to *In review* with its report, for you to close it. A session
that left files changed, or says it changed the code, is still blocked
(`session.no-commit`).

The comment asks *Writing or Publication?* and says which is the more careful of the two —
in doubt, always the one further along *Writing → Code → External action → Publication*.
**The Type column is left empty** rather than filled with that guess: a type the runner
wrote would read, the next time, as a type you had chosen. Pick it, or answer: the
question offers one button per type, in the console and on your phone, and the daemon
writes the type you clicked — or named in a sentence, *action externe*, a typo apart
(*readction*), or by its number — into the column, then runs the ticket without asking
again. An answer that names two types, or none, goes back to the classification.

**A type somebody chose is never touched.** Not overwritten, not re-classified, not asked
about. An option that is none of the four — a column you use for something else — is left
alone as well, and the ticket runs by its project as it always did. A board without the
column at all, or `runner.classify = false`, is the runner exactly as it was; `ponos
init` adds the column to an existing board, and `ponos doctor` says which of the
four options it offers. A ticket typed in English before the names were fixed — *Writing*,
*External action* — is still read as its type.

**A ticket run as the wrong type corrects itself, once.** A *Writing*, *External action* or
*Publication* ticket on a project that has a repository is told where that repository is,
and that it may not change it. When what the ticket asks for is precisely a change there, the
session writes no answer and ends on a `KIND: code` line instead of asking to be run again:
the runner writes *Code* in the column, says so in a comment (*↩️ Back in the queue*), and
puts the ticket back in *Ready* — the next free place runs it in a worktree, with a fresh session,
and nothing is asked of you. Only once a ticket: a second `KIND: code` on the same ticket is
not believed, and it stops as its session did, for you to look at.

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

### A diagnostic: the cause, then the tickets that fix it

A sentence like *the chat does not work* makes a vague ticket, and a vague ticket gets fixed
on a guess. A **Diagnostic** ticket does the investigation first: its session finds why,
proves it, and writes the tickets that fix it — at the level of detail of a ticket written
by hand — and Ponos creates them on the board.

**It starts from a sentence.** The title is the symptom as you would say it, the project is
optional. Four ways to write one:

- the console: **Diagnose** in a project's header, or *Diagnose a problem* in the command
  palette (Ctrl/⌘ K) — the *New ticket* dialog, its type already *Diagnostic*;
- the console's chat: `> diagnose "the emails do not go out" --project Leadz`;
- the CLI: `ponos diagnose "the emails do not go out" --project Leadz` — *Ready* at once,
  `--draft` to leave it in the drafts;
- the MCP: `create_task` with `type: "diagnostic"` (a draft, as every task the MCP creates).

**It reads, and changes nothing.** Like a *Writing* ticket it is given no worktree and no
branch, only the project's repository to read — `origin/main` first, its history, its recent
pull requests — and Ponos's own state and logs. On top of that, what the project declares on
its **Settings** tab, card *Diagnostic*:

| Declared | What the session may do with it |
| --- | --- |
| **Admin MCP servers** — their names in `claude mcp list` | call their tools that read: health, recent errors, status, configuration |
| **SSH hosts** — `user@host`, the vault entry that opens it, what the machine is | read-only commands (`cat`, `journalctl`, `systemctl status`, `docker logs`…). The entry is handed to that session alone, by name, as for [the vault](configuration.md#ponoss-own-vault-context--vault) |
| **Production addresses** | `curl`, GET only |

Nothing in that list is a write access, and the session is told the rest: no commit, no
push, no write in production, no restart, no deployment, no message sent. Dokploy or Umami
are read the same way, through their MCP server or their address.

**What comes back**, once the cause is found:

1. the **report**, in the ticket's page: the symptom, the cause with its proof — files and
   lines, log extracts, commands and what they answered —, what remains uncertain;
2. the **fix tickets**, written by the session in `FIXES.json` and created by Ponos: each one
   with its *Context*, *Expected*, *Done when* and *Out of scope*, in the diagnostic's
   project, of the type and sub-type the session gave it, and
   [« after »](tickets.md#a-ticket-that-comes-after-another) the diagnostic and the fixes it
   depends on — a relation the runner waits on, not a sentence in a text. A file Ponos cannot
   read creates nothing at all, and blocks the diagnostic with the reason;
3. the diagnostic goes to *Done*, and its comment lists the tickets created.

The fix tickets are **drafts** by default, for you to read. *Fix tickets straight to Ready*,
on the same card, sends them to *Ready*: each one starts as soon as what it comes after is
done — the diagnostic first, which closes in the same breath.

**No cause, no ticket.** A session that cannot find the cause stops in *Blocked*, with what it
checked and ruled out in its report and the precise question that would let it go on — an
access, a log, a fact only you know. Whatever it may have left in `FIXES.json` is not read: a
fix written on a guess is what this type exists to avoid. Answer, and it starts again.

It starts on the *heavy* level of [the model of a ticket](#the-model-of-a-ticket)
(`auto_model_diagnostic`, a constant of the code rather than a key of the file), and fixing in the same session is out of its scope: it
writes no code.

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

**An option the runner does not write** — `Improvement` beside `Amélioration`, `Security`
beside `Sécurité`, left by an older Ponos or typed by hand — is read as the same sub-type,
but a Notion view filtered on one misses the tickets on the other. `ponos doctor` and the
console's health band name each such option with its number of tickets, and the console
offers to fix it: the tickets move to the runner's option, then the emptied options are
removed from the select. An option that spells no sub-type at all is left to you.

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
chosen and how it ended is kept in the local journal, so this works the same with Notion
or without. Through OpenRouter, name its slugs in the four levels.

**Fable is off.** It costs far more than Opus, so `runner.use_fable` is a constant,
`false` — it is no key of the file any more — and nothing the runner starts runs on it: the *heaviest* level, and
any level whose model is `fable`, runs on `opus`, an escalation stops there, a session
begun on Fable carries on on Opus, and a `Model` of `fable` written on a ticket or its
agent runs on Opus too — its report says *Fable is turned off in the settings: run on
Opus.* The console's chat, the naming and classifying sessions and the conflict
resolution follow the same rule. Turn it on to get the behaviour above unchanged.

### Following the work

#### Live, on the ticket itself

A run used to say nothing between *In progress* and the pull request. Now it narrates,
in two places that answer two different questions — and neither of them is the ticket's
page, which holds the mission and what was done (see
[A ticket's page: the mission, and what was done](tickets.md#a-tickets-page-the-mission-and-what-was-done)).

- **The `Progress` column** carries the last step, on a ten-second cadence, so a glance
  at the board — from a phone, without opening anything — shows which ticket is on
  `Bash · npm test` and which is still reading. With a plan (the agent's todo list) it
  says how far the plan is: `3/5 — writing the tests`. It is cleared when the run ends:
  « What was done », the comment, the status and the pull request speak from then on.
- **The console's live tab** has every step — what the agent said, whole and in its own
  markdown, and each command, file read and edit between — read from the run journal
  (see [The run journal](troubleshooting.md#the-run-journal)); `ponos logs -f` streams
  the same from a terminal. The *Session* column of the board, and each line of the
  history under « What was done », lead there.

What the agent *says* is shown as it said it, in that column and on the console's card
under *Ponos is working…*: the run does not rewrite it into a step of its own. So it is
the prompt that sees to its language — with `runner.language` set, the sentence that asks
for the report in that language asks for these lines too, as short, whole sentences
rather than notes the agent leaves itself (“Now delivery around the claim.”). Without it,
the agent keeps its own habits, which are often English.

A **cadence, not a stream**: a session emits several events a second, and writing each one
would spend the integration's rate limit for a line nobody can read that fast. Ten seconds
is the default, five the floor:

```toml
[runner]
progress = true
progress_interval_seconds = 10
```

A board with no `Progress` column, or an integration that refuses the write, costs the
line and nothing else — the ticket runs to its end either way. `ponos init` adds the
column to an existing board.

Runs before this used to append a toggle per session to the page — `✓ 27 steps · 6
minutes · removed the header`. Those still on a page are recognised by their title, left
out of every brief, and taken away when the page is put in its two parts.

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
command that resumes it, with the log path, is said under the report on the days a run
went wrong. On the other days nobody has ever needed them.

The same line also travels into every prompt, so the summary at the top of a report, the
document a ticket with no repository produces, the answers given in the comments and the
sentences the session says while it works — the `Progress` column, the console's live
tab — are written in it too. What it does *not* touch is the repository: commit messages, code and
identifiers keep the language the repository already uses, because a branch is read by
whoever works on it and not by whoever asked for it.

**Empty — the default — is English, and it is more than that: it means nobody decided.**
Each session then keeps the rule its prompt already carries — answer in the language the
ticket is written in, reply in the language you were written to — so a ticket written in
French comes back in French, under a report written in English. That is the runner as it
has always behaved, and naming a language here is what replaces it with a decision.

Everything the runner writes where you read it follows the setting: the comments under a
ticket, the two headings of its page (« Mission », « Ce qui a été fait ») and its history
(`12 minutes · 1,50 $`), the line that resumes
the session, the body of the pull requests it opens, the note about a branch a ticket
already had, the line a ticket born of a schedule opens with, the answer it relays from
Telegram or Slack, and the desktop and phone notifications. Only an error is quoted as it
came — git's, GitHub's, Notion's — because it is evidence, not a sentence. The journal on
the terminal and the CLI stay in English: they are read by whoever is standing at the
machine, and half of what they print is argparse's, git's or GitHub's. Translating only the
other half would put two languages on the same screen, so `ponos`, typed alone, says it
instead — *The CLI speaks English; the console follows runner.language (fr).* — whenever
the file names a language other than English.

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
ticket: `ponos projects`, `ponos list` and a dry run download nothing,
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
creates it, through the same store as everything else — a Notion page, or a row of `board_pages` without
Notion — in the columns the projects database already has (`github` rather than a
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

Add a `Rôle` relation column on your tickets, pointing at a database of agents. One row
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

All of it is optional twice over: a tickets database with no `Rôle` column behaves exactly
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

The columns may be written in English too — `Criterion`, `Due`, `Status`, `Projects` (or
`Projet`, `Project`), `Priority` —: the runner, the ideas and the console read them under the
same names, the French first.

A ticket that points at one carries it into its prompt, under `# L'objectif — <name>`, with
its criterion and its due date. Only the first goal of the relation is read, and only while
it is still worked toward: a goal whose `Statut` is anything but `Actif`, `Active` or
`En cours` (met, given up, on hold), or one in the trash — what *Delete* does to a goal in
the console —, is left out of the prompt, as if the ticket pointed at none. A goal with no
`Statut` counts as active. Its place is fixed:

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
the goals is the console's [Goals](console.md#goals) page (how it counts a goal's tickets, and
the Notion rollups that agree with it: [How a goal's tickets are counted](console.md#how-a-goals-tickets-are-counted)), the [ideas](console.md#ideas) (the active goals of the
scope, under « Les caps du moment ») and the MCP connector's `list_goals` and `create_task`.
Without Notion the database is the `goals` collection of `board_pages`, with the same columns.

All of it is optional twice over: a tickets database with no `Objectif` column, an empty
relation or a goal page the integration cannot read all give the prompt you had before, to
the character. A workspace without the `Objectifs` row says so once per run, and runs.
