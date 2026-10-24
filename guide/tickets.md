# A ticket's life

[The guide](README.md) · [Ponos](../README.md)

From the discussion on a ticket to *Done*: the statuses, the review, *Validated*, and the tickets that come back on their own.

## The discussion on a ticket

The comments of a ticket go into the prompt, oldest first, which closes the loop the
`blocked` status opens: a run asks a question, you answer it in a comment — and the next
run reads your answer instead of asking again.

**Answering is the whole gesture.** The reply itself puts the ticket back in the queue:
nothing to move on the board, the runner claims it and it goes to *in progress* for as
long as the new run lasts. Which is narrow on purpose, because not every comment is an
instruction:

- only tickets **the runner has already reported on** wake up. A comment on a ticket no
  run of ours ever touched is a conversation of yours, and one handled by another machine
  is that machine's to pick up — which machine ran it is the board's *Runner* column;
- only when **someone else has had the last word** since that report. The report the next
  run posts is also what closes the ticket again;
- and never a ticket that came back with its pull request. *In review*, *Validated* and
  *Done* are all answers already: comment on one and nothing happens — the discussion
  belongs to the pull request, and a validated ticket is about to be carried out. A ticket
  already ready, or one in flight, is left where it is too.

So it is `blocked` and `failed` that come back to life, which is where a run leaves a
ticket it could not finish, and precisely where an answer is expected.

The runner's own reports are included too, trimmed to their verdict and reason; the branch
names, session IDs and log paths they carry are of no use to a session. At most the last
ten comments and 2000 characters, newest kept, so a ticket that has been round three times
does not spend more of its prompt on its own history than on the work.

This needs one capability the integration does not have by default:
[notion.so/my-integrations](https://www.notion.so/my-integrations) → your integration →
**Capabilities** → *Read comments*. Without it the runner says so once and carries on —
and no ticket ever wakes up, since it cannot see the answer. `ponos doctor` tries
it on a real ticket and tells you.

## Talking to it in the comments

Running a ticket again is the right answer to *do it differently*. It is the wrong answer
to *why did you do it like that?* — which is most of what one actually wants to say to
something that has just written code on one's behalf.

So a comment can also simply be **answered**. Reply under one of its reports and it
replies, in the same thread, in the language you wrote in:

> **✅ To review — PR #12 · 2 commits · 9 minutes · $0.74**
> Removed the header from the dashboard.
> <https://github.com/…/pull/12>
>
> > **you** — pourquoi une nouvelle branche plutôt que celle d'hier ?
> >
> > **Ponos** — celle d'hier était déjà partie en revue sur la PR #11, et y
> > pousser aurait mélangé deux changements sans rapport. La nouvelle part de `main`,
> > qui contient déjà #11.

Nothing is claimed, no status moves, nothing is built. It reads the ticket, the thread,
the project's brief, the context page and — for a ticket that has a repository — the
repository itself, and it answers. Then it stops.

**It talks, it does not work.** That is not a promise made in a prompt: the session runs
under `reply_permission_mode`, which is `plan` — a mode Claude Code cannot write from. Ask
it for a change and it tells you what the change would take, which is the beginning of
your next ticket.

And it is careful about whose voice is whose. Its reports, and the answers it writes here,
are the runner speaking; an answer relayed from
[Telegram or Slack](channels.md#being-told-and-answering-with-one-word) wears the same token and is
you, so that one still wakes the ticket. Only the first kind is ever treated as the last
word.

Three rules decide when it speaks, and all three are about knowing who is being spoken to:

- **a thread it already speaks in belongs to it.** Reply under a report and it answers. A
  new remark elsewhere on the page is a conversation of yours, and stays one;
- **naming it works wherever it is looking.** `@claude`, or whatever `notion.mention`
  says, or the integration's own name as Notion writes it when you @-mention it. That
  covers every ticket it has ever reported on, whatever column that ticket is in now, and
  every ticket that is not settled — `blocked`, `failed`, or with no status at all;
- **work wins over talk.** A plain answer under the question a `blocked` run asked still
  puts the ticket back in the queue: that loop is what `blocked` is for. Naming it is how
  you ask for words instead — `@claude pourquoi tu demandes ?` gets an answer, and leaves
  the ticket exactly where it is.

And it never answers itself. Every comment it writes comes back to it on the next pass, so
it asks Notion for its own user ID and compares identifiers rather than trying to recognise
its own signature. When Notion will not say — a token without the reach, a network that is
down — it says nothing at all that pass. A conversation with oneself is the one failure
mode here that would never end.

A thread is one long Claude Code session, resumed: ask a second question and it lands in
the same conversation as the first, which is why the second answer knows what the first one
said. `claude --resume` in a terminal opens that very session.

The pass runs on a cadence of its own — `reply_interval_seconds`, sixty by default —
because a comment does not change a page and Notion has no way of being asked *what has
been commented on since*. So it looks where a conversation can plausibly be: the tickets a
run reads anyway, and the pages it has spoken on, `reply_scan` of them per pass with the
window moving each time. A ticket sitting in *Ready* that it has never touched is the one
place it is not listening — and that one is about to be run, which is where your comment
was going to be read regardless.

Answers never come before the work. In a pass with tickets ready, the tickets take their
places first; the answers — and the look at the blocked tickets, below — then take one
place of `max_concurrent` between them, one session after the other, so what runs at once
stays capped whatever is waiting. With every place taken, they wait for the first one that
frees. A pass with nothing ready answers up to `max_concurrent` threads side by side.

| Where you write | What happens |
| --- | --- |
| under a report, on a `blocked` or `failed` ticket | the ticket runs again, with your answer in its prompt |
| under a report, naming it | it answers; the ticket does not move |
| under a report, on a ticket in review or done | it answers |
| a new comment naming it, on a ticket it has run or one not yet settled | it answers |
| a new comment naming it, on a ticket it has never touched | nothing — it is not looking there |
| anywhere else | nothing — not every comment is addressed to it |
| on a ticket about to run, queued, or scheduled for later | nothing: that comment is already going into its prompt |
| from Telegram or Slack | that is an answer, not a question: it wakes the ticket, as it always did |

Turn the whole thing off with `reply = false` under `[runner]`, and a comment goes back to
being only what it was: the thing that wakes a blocked ticket.

## Looking again at what is blocked

A ticket stays *Blocked* until someone remembers it — and the cause is often gone by then:
the ticket it waited for is done, the missing information is on the page. With
`unblock = true` under `[runner]`, the runner goes back over the column by itself.

For each blocked ticket it starts a session that cannot write (`reply_permission_mode`),
shows it the page, the discussion and every ticket of the board, and asks two things: why
did it stop, and is that still true? The session ends on `DECISION: unblock` or
`DECISION: keep`, with a `REASON:`. Only an `unblock` that gives its reason moves the ticket
back to *Ready*; a session that does not conclude changes nothing.

Every decision is traced. On the ticket, a comment says *No longer blocked* (with a
`↩️ Back in the queue` report, like a ticket put back in the queue) or *Still blocked* and
why — the latter only when the reason changed, not every time it is checked. In
`ponos history`, the entry is `unblocked` or `kept-blocked`, with the reason.

It is deliberately slow and small: a ticket is looked at once every
`unblock_interval_seconds` (six hours by default), three tickets at most per pass, and never
one edited in the last hour — a question asked just now is waiting for its answer. A ticket
already answered in a comment is left to the usual way of waking.

## A prompt on every change of status

Write a prompt in the ticket's `On` column and Ponos runs it each time the ticket's
status changes — whoever changes it: you in Notion or in the console, or Ponos itself
(*Ready → In progress*, *In review → Validated*, → *Blocked*…). The session is told the old
status, the new one and the ticket (title, page, discussion with the last report, project,
pull request, cost), and the prompt decides what the transition is worth. One prompt for
every transition, so it says which ones concern it:

> If it goes to **Validated**, create the deployment ticket in the *Infra* project. Any
> other change: do nothing.

It is the same text field on a Markdown board (an `On:` line in the ticket's front matter),
and in the console, on the ticket's page under its brief, with the list of its executions:
the transition each answered, its state, what it cost, how long it took and what it said.
`ponos init` adds the column to a board that does not have it; `ponos doctor` says if it is
missing. Settings › Prompt on status change turns it off (`runner.on = false`).

How it behaves, because a prompt that acts on its own needs limits:

- **Seen, not told.** The board is read at most once in `runner.on_interval_seconds`
  (30 s), only the tickets whose `On` is filled. The first time a ticket is seen is its
  starting point, not a change — turning this on does not replay your board. Two changes
  between two readings are one change, from the first status to the last.
- **Once per transition.** A change is written down in `ponos.db` in the same transaction
  that moves the ticket's remembered status forward, so a restart never runs it twice. An
  execution a dead run left open is closed as interrupted and not started again; one that
  could not start for want of credit is simply run later.
- **No loop.** Every status changed while an execution ran — its ticket's included — is
  taken as the new starting point without running anything, and a ticket the execution
  created is one generation below it: past `runner.on_max_depth` (3) its changes run
  nothing, and say so in the list. A status you change by hand during those minutes is
  lost to the prompt.
- **A ceiling on each execution.** `budget.on_usd` (1 $) is handed to the session as
  `--max-budget-usd`; `runner.on_timeout_minutes` (10) stops it by the clock. It acts, so it
  runs under `runner.permission_mode` unless `runner.on_permission_mode` says otherwise —
  in a scratch directory of its own, never in your repository: work for the repository is a
  ticket it creates.
- **Errors stay on the ticket.** A failed, overspent or timed-out execution is logged,
  commented on the ticket (`⚠️ The « On » prompt failed on Ready → Blocked: …`) and never
  changes its status. It is also a line of `ponos history` (`kind: on`) and counts in the
  day's spending.

## The statuses

This is where your control over the system lives. The names are yours — map them under
`[notion.status]`, and `ponos doctor` checks each one actually exists on the
board, because a status the database does not offer would only fail at the very end of a
ticket.

`ponos init` creates these eight:

| Key | Default | What it means |
| --- | --- | --- |
| `ready` | **Ready** | the description is precise enough for an agent to handle it alone. **The gesture that triggers work** — the other being a comment answering a ticket already handled once. |
| `running` | **In progress** | claimed by the runner. Stops the next run from taking it again. |
| `review` | **In review** | branch pushed, pull request opened. Yours to review. |
| `validated` | **Validated** | you read it and said yes. **The second gesture that makes the runner act** — it merges the pull request, or publishes what the ticket holds, and then closes it. |
| `done` | **Done** | that pull request has been merged — or the ticket produced a document, which has nothing to wait for. |
| `failed` | **Failed** | something broke: the session, the push, the worktree. |
| `blocked` | **Blocked** | the agent would not guess and asked a question instead — or its project could not be located. Answer in a comment and the ticket runs again. |
| `paused` | **Paused** | you stopped it on purpose, from the console, while it was in progress: its session is ended and its worktree and branch kept. The runner **never takes it back by itself** — not from a comment either; only moving it to *Ready* (**Resume**) runs it again, and the new session opens on the work already there, as for any ticket that has run before. *Optional*, like *Cancelled*: `ponos doctor` says so, and `ponos init` adds it to a select. |
| `cancelled` | **Cancelled** | you gave up on it. **Terminal**, like *Done*, and not *Done*: the runner never runs it — not from *Ready*, not woken by a comment, not even named with `ponos run --ticket` — and the statistics count it neither closed nor open, though what its sessions spent stays in the spending. *Optional*: a board without the option simply has no such gesture; `ponos doctor` says so, and `ponos init` adds it to a select (on a Notion *status* property, add the option by hand). |

<a id="why-a-ticket-stopped"></a>**Why a ticket stopped** is a code, not only a sentence. Every
stop the runner decides has its cause in a catalogue, `src/ponos/blocks.py`: a code
`domain.cause` — `merge.checks-failed`, `merge.base-moving`, `merge.conflict-decision`,
`session.question`, `session.no-commit`, `worktree.residue`, `notion.write-failed`… — a
family (merge, session, infrastructure, question, access), who has to move (Ponos, you,
or GitHub and Notion), a label and a line of help in both languages, the gesture it
proposes (run it again, answer, clean, look at the CI or at the pull request) and what the
runner may do about it alone (`retry:n`, `wait-base`, `ask`). The code goes into the
history and the run in `ponos.db`, into the `Blocage` select of the board — one option per
code, coloured by family, created by `ponos init`, and named by `ponos doctor` when it is
missing — and onto the card in the console: a badge with the family's icon, the help under
it, and the gesture first among the buttons. The search over the board filters by it, and
the statistics count it week by week. The history written before codes existed was read
back from its sentences, French and English, when `ponos.db` was migrated; a sentence that
matched no cause is counted as `unknown`.

<a id="ci-on-the-card"></a>**CI on the card.** A ticket in *In review* with a pull request shows
whether its checks pass, without a trip to GitHub. Each pass asks `gh` for the checks of the
open pull requests of that column — every 30 seconds while one is running, every five
minutes once settled — and keeps the answer in `ponos.db`; the console reads it with the
list, so opening the board or a card asks GitHub nothing. Three states: `en cours` (a check
is waiting or running), `réussi` (all of them finished green, skipped ones included),
`erreur` (one failed, was cancelled or timed out — a red check wins over a running one).
A pull request with no check shows nothing, never a green. A push puts it back to `en cours`
until the new commit's checks are in. The state is also written to the `CI` select of the
board, so a Notion view can filter on it. A ticket that leaves *In review* is no longer
followed.

Four of those names are deliberate. *In review* rather than *Done*, because nothing is
done when the runner lets go of a ticket: a pull request is waiting for a human, and a
board that calls that *Done* stops being believed by the second week. *Done* is then kept
for what it says — merged, published, out. And *Blocked* is its own column rather than a
shade of *Failed*, because the runner works hard to tell them apart — a ticket waiting for
**you** and a session that crashed are different days, and pouring both into one column
throws that away.

There is deliberately **no column for "the credit ran out"**. A ticket the subscription
ran out under is waiting for nobody, so letting it into *Blocked* would have made the one
column that means "you are needed" also mean "come back at six" — but an eighth column of
its own would have been just as wrong, because nothing happened to that ticket. It is
still ready. So it stays where it is and is *ticked*, in a **Waiting for credit** checkbox
— an attribute of the ticket, not a moment of its life. See
[the tickets database](board.md#the-tickets-database).

*Cancelled* is the other end of a ticket, beside *Done*: given up on, not finished. Filing
the tickets nobody wants any more under *Done* is how *Done* stops meaning "this got done".
In the console it is a column of its own, last, its dot a hollow grey and its cards struck
through; a card offers **cancel the ticket** behind its "…", a cancelled one offers
**reopen**, which sends it back to the drafts — not to *Ready*, since a ready ticket starts
a session that is paid for. *Abandon* on a blocked ticket and *Reject* on one in review
file it there too, on a board that has the column.

*Paused* and *Abandon* are the two gestures of a ticket in progress, on its card and on its
page. Both go through the same move as any other: the console first asks the run that holds
the session to end it (a file under the state directory, `stops/` — the session is a child of
another process, and a signal from outside would be read as a kill and retried), waits for it
to say the session is gone, and only then touches the worktree. **Pause** commits what the
worktree holds, as a save, and keeps it; **Abandon** asks first, removes the worktree and
files the ticket under *Cancelled*. A session already dead, or stuck, is not waited for, and
the same move works — a ticket moved to *Paused* or *Cancelled* from anywhere else, a dragged
card included, is stopped the same way. One short line is left on the ticket (« Mis en pause »,
« Abandonné »), nothing of the machinery.

*Validated* is the fourth, and the odd one: every other column **reports**, this one
**asks**. It is the answer to the question *In review* puts — is this what you wanted? —
and moving a ticket there is you saying yes, go on. See
[Validated, and what it sets off](#validated-and-what-it-sets-off).

One column for two states is still a fine board, if yours is small. Name `failed` and
leave `blocked` out, and questions land wherever failures do; name `done` and leave
`review` out, and a ticket stops at its open pull request. A file that names its columns
and does not name `validated` has no validation gesture either — nothing is merged or
published for you, exactly as before:

```toml
[notion.status]
done = "Shipped"
failed = "Needs you"
```

An eighth key, `draft`, is optional and has no default: it names the option your board
**already has** for a ticket still being written — `ponos init` creates none, and
the runner never writes nor picks one up. Named, the console draws those tickets in a
*Draft* column of their own (*Brouillon* in French), first, and *New ticket*'s *Draft*
button puts the ticket there; `doctor` checks the option exists and is none of the seven
above. Left out, a draft has no status and sits in that same column, as before:

```toml
[notion.status]
draft = "draft"
```

## Merging is the only gesture

A ticket that came back as a pull request waits in *In review*. Every run then asks
GitHub — through `gh` — what became of those pull requests, and a ticket whose own has
been **merged** moves to *Done*, with a comment saying so. So you merge, and the board
catches up on its own; nothing else to close by hand.

The cadence is the runner's own: `interval_seconds`, not a second timer to install and
forget. A ticket whose pull request is still open, closed without merging, or unreachable
because `gh` is not authenticated simply stays in review — the next run asks again. A
board whose `review` and `done` are one column has nowhere for a ticket to wait, so
nothing is watched.

Nothing is ever merged behind your back. The decision is yours; only its consequence is
not — and if you would rather not make the merge itself either, the next column takes it
off your hands.

## Ten tickets on one repository

The base branch does not wait for a session. Ten tickets aimed at one repository means ten
sessions that started on the `main` of an hour ago, and the first merge makes the nine
others conflict — which is how a board that was working becomes a morning of rebasing by
hand. `runner.rebase`, on by default, is the answer, and it is the same gesture in two
places.

**Before the pull request.** The branch is replayed onto its base between the commits and
the push, so what opens is a pull request on top of what the repository holds *now*. A
rebase that hits a conflict changes nothing: the branch goes back exactly as the session
left it, the pull request opens all the same, and the conflict is written on the ticket —
where somebody will read it — rather than discovered on GitHub a day later.

**When a validated merge is refused.** A pull request opened this morning is behind by
noon. GitHub refuses the merge, and that refusal is about the *branch*, not about the
work: the branch is replayed onto its base, pushed with a lease on the very commit that
was replayed, and the merge is asked once more. The ticket says so and goes to *Done*. The
runner does not even wait to be refused: it asks GitHub first (`gh pr view --json
mergeable,mergeStateStatus`), and a pull request already called *conflicting* or *behind*
is replayed before any merge is asked. A refusal a rebase does not answer — a check still
red, a review still missing, a branch whose policy forbids the merge — is left as it came:
the ticket goes to *Blocked* with GitHub's own wording, and nothing is pushed a second time.

**When the replay conflicts.** Two tickets touched the same lines, the first was merged,
and the second no longer replays cleanly — “Pull Request has merge conflicts”. With
`resolve_conflicts`, on by default, that is no longer yours to sort out:

1. The branch, as GitHub holds it, is checked out in a disposable worktree of its own
   and rebased onto `origin/<base>`. The rebase is left where git stopped.
2. A session is started there — on the ticket's model, or `resolve_model` — and told the
   ticket, the pull request's description and diff, the commits that landed on the base
   since the branch left it, and the files git stopped on. It keeps **both** intentions,
   and never drops another ticket's work to make this one pass; lockfiles and generated
   files are regenerated rather than merged by hand, changelogs and changesets keep every
   entry. It carries the rebase to its end and runs the project's checks — whatever its
   CLAUDE.md, `package.json`, Makefile or CI define — fixing what the merge broke, three
   attempts at most. It pushes nothing: it takes a place like a publication, and the
   ticket shows *In progress* while it works.
3. The runner checks what it left — no rebase half done, no conflict marker in a file,
   the base underneath — then pushes with `--force-with-lease` on the very commit it
   replayed. Never `--force`, and never the base branch.
4. When the repository has a CI (`.github/workflows`), its checks are waited for, up to
   `checks_timeout_minutes`; then the merge is asked again. A red check is not taken at
   its word: the failed GitHub Actions jobs are run again once (a flaky test goes green
   and the pull request is merged), and a check still red is compared with the newest
   commit of the base — red there too, the base is the one that is broken, not the pull
   request. The ticket is then set aside in *Validated* (“the base is red, it is not this
   pull request”, `merge.base-red`), no session is started again and nobody is asked
   anything; one ticket “Repair `<base>` of `<project>`” is opened in *Ready*, type *Code*,
   sub-type *Bug*, at priority 75, with the failing jobs and the link of their run — never
   a second one while it is open. Its pull request is validated without waiting for you,
   whatever *Force validated* says: once its CI is green it is merged by the runner, since
   every other pull request of the repository waits behind it. And at every pass the base is read again: once those checks are no longer red
   there, the pull request goes on by itself. `ponos doctor` and `ponos projects` say when
   a repository's base has no CI run at push, or only skipped ones: that is how a red base
   goes unseen.
   A check that is red here and only here is not a question yet: a session is sent after
   it, on the branch of the pull request, told the names of the red checks and the end of
   the log of their failed jobs (`gh run view --log-failed`, cut). It fixes what the branch
   broke — not the base, no test turned off — and commits; the runner pushes it with the
   same lease, waits for the CI again and, once it is green, merges as usual. One attempt
   per ticket and per head commit, kept in `ponos.db` (table `mends`, like `write_ups`): the
   same red never costs two sessions. If it answers *blocked*, commits nothing or the CI is
   still red, the ticket is blocked as before (`merge.checks-failed`), with the session's
   report on the card.
5. The pull request gets a comment, and the ticket gets its report: the commit it was
   rebased onto, the files in conflict, how each was resolved, what the checks said. The
   session's cost is added to the ticket's *Cost*.

It stops and asks instead — *Blocked*, as before, but with the conflict and the question
rather than GitHub's refusal — when the session judges a conflict to be a decision (two
behaviours that cannot both hold, code deleted on one side and changed on the other, a
schema or a migration changed on both), when checks still fail here and not on the base after
the repair session (the report names them), when somebody else
pushed to the branch in the meantime (the lease refuses to overwrite their commits, and
the ticket says so), and when the base keeps moving: a ticket's branch is replayed twice
at most before it asks. Whatever resolution was reached is pushed on a branch of its
own, `<branch>-rebased-<commit>`, for you to look at. A project named in
`resolve_conflicts_except` keeps the old answer: its conflicts block the ticket.

Set `rebase = false` and all of it goes away: the branch is pushed as it was written, and
a merge refused is a question, as before.

**Generated files and the changelog never reach a session.** Nearly every conflict of a
busy repository is in a bundle a build writes (`src/ponos/web/static/**`) or in
`CHANGELOG.md`, and neither is a decision. A replay settles them itself, wherever it runs —
before a pull request opens, when a merge is refused for being behind, and at step 1 above:

- `CHANGELOG.md` is merged by union, whatever the project: both sides are kept, the base's
  entries first. Nothing to declare.
- A project declares its generated files in a `.ponos.toml` at the root of its repository
  (read from the base, not from the branch):

  ```toml
  generated = ["src/ponos/web/static/**"]
  build = "cd frontend && npm ci && npm run build"
  ```

  A conflict on one of those paths takes the base's version. When the replay reaches its
  end, `build` runs in the replay's worktree and what it wrote is committed on top
  (`Regenerate the generated files`), only if the branch changes a generated file at all.
  A build that fails stops the replay: bundles that do not match their sources are not
  pushed. Without a `build`, the base's version simply stays.

A session is started only if a conflict is left in hand-written code — and it is then
given the list without the files that were settled.

**One merge at a time per repository.** The merges of a repository wait in a line — the
validated ones of the pass and the forced ones of the sessions alike — and each pull
request is replayed onto the base as the merge before it left it, just before its own
merge. Three validated pull requests on one repository merge one after the other, and
the base no longer moves under a replay in progress (the *“`main` keeps moving faster”*
block). The line is held across the replay and the merge, never across a wait for CI.

## Validated, and what it sets off

Reviewing ends in a gesture. You read the pull request and it is good: someone still has
to press *Merge*. You read the post the agent drafted and it is right: someone still has
to publish it. That last step is the one the board has always left to a human — and it is
the one part of a ticket that is pure mechanics.

*Validated* is where you hand it over. You move the ticket one column to the right, and on
its next pass the runner does the last thing the ticket needs:

```
Notion                    Ponos                               what happens

In review     ──────▶     you read it. Good?
    │
    └─ yes ──▶ Validated  ─┬─ the ticket has a pull request
                           │      gh pr merge --squash              ──▶  it is in
                           │
                           └─ it has none: a post, a mail, an announcement
                                  a session, told to publish what the
                                  ticket already holds                ──▶  it is out
Done          ◀───────────  and only then
```

**A pull request** is merged with `gh`, the way `merge_method` says — `squash` by default,
`merge` or `rebase` if that is your repository's habit. One that has fallen behind or
conflicts with its base is replayed and, if need be, resolved first — see *Ten tickets on
one repository* above. One that GitHub refuses for anything else — a check still red, a
review still required — puts the ticket in *Blocked* with GitHub's own wording in a
comment, because that wording is the answer. One already merged
by hand between two passes just moves to *Done*. One closed without merging is a question,
not a merge: *Blocked*, and the ticket says so.

**A ticket with no pull request** is the other half, and the interesting one. The work
already exists — an earlier run wrote it into the page, and you have just read it — so a
session is started with one instruction: *publish this, do not rewrite it*. What
publishing means comes from the ticket itself: post it to that account, send it to that
list, put it on that page. It uses the tools the machine actually has (an MCP server, a
CLI, an API key in its environment) and, where it has none for the job, it says so and
stops rather than improvising — the ticket lands in *Blocked* with what is missing. Then
*Done*, with a comment saying where the thing went.

That second road is for tickets that have no repository — and for every ticket whose
`Type` took it off one, a *Publication* first of all: [prepared in review, published once
validated](board.md#the-type-of-a-ticket). A ticket **on a repository** with no pull request and no
such type has nothing to merge and nothing on its page to publish, so it is not guessed at
either: it goes to *Blocked* asking where its pull request went.

So the board reads end to end: *Ready* is you asking for the work, *Validated* is you
accepting it, and *Done* means it is actually out in the world rather than merely
finished. Between the two, the runner does the typing.

Five things are worth knowing:

- **the column is opt-in.** A board whose `Status` does not offer *Validated* is never
  even queried, and everything behaves exactly as it did — you merge by hand, and
  *In review* → *Done* stays yours. `ponos init` adds the option to an existing
  board (a real Notion *status* property cannot be widened through the API: `init` says
  so and you add it in one click). A configuration that names `review` or `done` under
  `[notion.status]` without naming `validated` describes a board that ends at the pull
  request, and gets no gesture either;
- **it is claimed like any other work.** A ticket being published moves to *In progress*
  while its session runs, so a second machine watching the same board cannot post the same
  thing twice. And a run that dies mid-publication does **not** put that ticket back in the
  queue: it may have posted seconds before dying, so it comes back as *Blocked* asking
  whether it went out, and one click on *Validated* tries again;
- **it comes before the queue, and never one at a time.** Merges and publications are
  settled at the top of a pass, before any new ticket is claimed — a ticket you have
  accepted comes before one nobody has read. Publications run side by side under
  `max_concurrent`, so four of them cost one session's wait rather than four;
- **and it never waits for what is in progress.** The column is read again every
  `interval_seconds` for as long as the pass lasts, whether or not a place is free: a
  pull request you validate at 14:20 is merged at 14:20 — a merge is two `gh` calls and
  costs no place at all — and a publication takes the next place that frees, ahead of
  the ready column. A validated ticket therefore never sits behind a two-hour session it
  has nothing to do with;
- **a date on the ticket still holds.** `Scheduled` says "not before this moment"
  wherever it is written, so a validated ticket dated Thursday is merged or published on
  Thursday rather than on the next pass. It is what makes the column a schedule and not
  just a *go*: you accept the post when you have read it, and it goes out when it should.
  `ponos list` shows those alongside the ready tickets that are waiting, and a
  pass says how many are;
- **it is never guessed at.** The runner acts on that column and on nothing else: no
  ticket is merged or published because a session felt sure of itself — only because you
  moved it, or ticked [*Force validated*](#force-validated-skipping-the-review) for its
  type beforehand. And
  `ponos run --dry-run` says what it *would* merge or publish without touching
  anything — this is the one gesture worth rehearsing.

## Force validated: skipping the review

For some types of ticket the review stopped earning its keep: you validate every pull
request of a project you trust, or every post of an account that only relays. One box per
type — **Code**, **Writing**, **External action**, **Publication** — in the console's
*Settings › Automatic validation*, or `force_validated_<type> = true` under `[runner]`, makes
that gesture in advance. All four are off by default, and nothing changes until you tick
one.

Ticked, a ticket of that type no longer stops in *In review*: as soon as its session has
succeeded, the runner does what moving it to *Validated* would have set off, then moves it
to *Done*. Its report says so, and says whose decision it was — *Validated automatically
(Force validated: Code) — the global setting*, or *— the project's setting*.

**Project by project.** The four switches above are every project's, until a project has
its own: on its page in the console, the *Settings* tab has *Its own automatic validation*.
Off — the default — the project follows the global switches, shown there read only with a
link to change them. On, it gets the same four switches of its own, started from what the
global ones said, and they are what its tickets follow, even where they contradict the
global ones — merging unread on a project of your own, every pull request read on a
client's, whatever `config.toml` says. They are kept in the runner's local database
(`ponos.db`), not on the board, and survive a restart; *Settings › Automatic validation*
names the projects that have their own, and so does `ponos doctor`.

- **Code** — the pull request is opened, its CI waited for (at most
  `checks_timeout_minutes`, only on a repository with workflows; a red check is run again
  once, and one the base fails too does not hold the merge back), then merged with
  `merge_method`, as a validated one is. A merge that is only *not yet* goes to
  *Validated* instead: a branch another ticket overtook while its CI ran (behind its base,
  or in conflict with it — GitHub is not even asked when it already says so), or a CI
  still running when `checks_timeout_minutes` runs out. The next pass merges it the way it
  merges any validated ticket — replaying the branch, resolving the conflict — without
  holding a session's place meanwhile, and the report says the merge was postponed and
  why. A merge that is a question — a check red on this pull request only, a review or a
  rule of the branch — is **not** done: it stays in *In review*, with the refusal in its
  report and on its card, and you take it from there as before. So does every refusal on
  a board with no *Validated* column;
- **Publication** — what the session prepared is published straight away by the
  publishing session, in the same pass. Under the credit reserve it goes to *Validated*
  instead, and the first pass with credit again publishes it;
- **Writing** and **External action** already end in *Done*, with nothing left to
  validate: their boxes are there for symmetry, and change nothing today.

Two guards hold whatever is ticked: a ticket whose session failed, was blocked or ran out
of credit is never validated, and the option only applies to tickets run after it is
switched on — a ticket already in *In review* stays there until you move it. Neither guard
is a project's to lift: its own switches only decide what the global ones would have.
`ponos doctor` says which types are forced.

---

## What comes back on its own

A ticket leaves once: you write it, you move it to *Ready*, it runs, it ends in *Done*.
Everything that **recurs** — Monday's dependency review, the report on the first of the
month, the weekly digest — is retyped by hand, or is not done at all.

The parti pris is what keeps the rest simple: no second execution engine beside the
runner, only **one more source of tickets**. A *schedule* is a row in a Notion database
that describes a ticket and how often it is born. When its moment comes, the runner
creates that ticket in the ready column — and from there on, everything is the code that
already existed. Same column, same queue, same session, same pull request. The schedule
only presses the button for you.

A row is the recipe. `Cadence` (Hourly, Daily, Weekly, Monthly), `At` (the hour, written
`09:00`), `Day` (Monday, or 1 to 31), and the `Active` tick that turns it on. Whatever
`Project`, `Model`, `Priority`, `Type` and `Sous-type` it carries, the ticket it makes
carries too — and the **body of the schedule's page is the brief**, copied into each
ticket, so the ticket reads on its own and its history shows what was asked for that day.
A ticket born with a `Type` is never classified: set it to *Code* on a schedule whose
tickets are code, or a long, well-written brief may well read as *Writing*. Three columns
are the runner's to write: `Next`, `Last`, and `Last ticket`.

```
Schedules                 Ponos                               Tickets

Active ✓, Next ≤ now ────▶ recur()
                            │
                            ├─ the last occurrence is still open? ──▶ skipped, and said
                            │
                            ├─ writes Next and Last          ──▶ the occurrence is taken
                            │
                            └─ creates the ticket            ──▶ Ready — body copied,
                                                                 Project / Model / Priority
                                                                 Type / Sous-type
                                                                 │
                                 the queue of the same pass  ◀────┘
```

`recur` sits between the validated column and the queue — before the queue on purpose, so
a ticket born at 09:00 is claimed by that very pass rather than by the next one.

**Two rules surprise people, and both of them are the point:**

- **catching up creates one occurrence, never the missed ones.** Machine off for three
  days, timer stopped, laptop shut: waking up gives you one ticket for the occurrence
  that is due, not twelve. `Next` is recomputed *from now*, never by stacking up what was
  lost. This is anacron, not cron — turning a laptop back on must not set off an
  avalanche of sessions;
- **an occurrence that is still open blocks the next one, and the pass says so.** While
  the ticket in `Last ticket` is neither *Done* nor *Failed* — so still ready, running, in
  review, validated, or blocked on a question nobody has answered — no second ticket is
  made. `Next` moves on regardless. Without that, one schedule stuck on a question fills
  the board with twenty copies of itself.

Three smaller ones, in the same spirit. **A schedule written this minute does not fire
this minute:** an empty `Next` is computed and written, and nothing is born — creating a
"Weekly / Monday" row on a Tuesday should not start a session on the spot. **The
occurrence is taken before it is acted on:** `Next` and `Last` are written first and the
ticket second, so a crash between the two loses one occurrence rather than making two —
and a second runner on another machine reads a `Next` that has already moved and does
nothing. **A schedule nobody can read holds nobody up:** an unknown cadence, an
unreadable hour, an absurd day, and that row is skipped while the others go on;
`ponos doctor` is where it is named.

```bash
ponos schedules                          # what repeats, and when it next happens
ponos schedules --run "Revue des dépendances"   # now, without waiting for Monday
ponos list                               # the whole calendar: tickets and births
```

The same calendar is a page of the web console — *Schedules* in the menu,
`/?view=console/schedules/list` — which is where you look at it from a phone, and where a
row is written and turned off without opening Notion. See
[The web console](console.md#the-web-console).

Everything here is optional. A workspace with no schedules page has nothing that repeats,
`doctor` is green on it, and nothing about it runs differently — `ponos init`
builds the database on a board that predates it, and `runner.schedule = false` turns the
whole thing off without a single row being unticked.
