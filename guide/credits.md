# Credits and limits

[The guide](README.md) · [Ponos](../README.md)

What happens when the subscription's window is spent, and how to stop before it.

## When the credits run out

A Claude subscription is metered in windows: a few hours of work, then the CLI answers
*usage limit reached* to everything until the window rolls over. A runner nobody is
watching reads that as every other broken session — and one spent window costs a whole
board, because each ticket it touches comes back as a failure with a log to read, and by
the time the credits return there is nobody left to put any of them back.

So it waits instead. When a session dies on the quota:

- **the ticket goes back to *ready*, ticked as waiting for credit** — and not to
  *blocked*, which is the column that means *you* are needed; a column that also means
  "come back at six" has stopped saying anything. A comment says why and asks nothing of
  you. Its branch, its worktree and whatever it had already committed are left exactly as
  they are, and so is its session: the pass that has credit again picks that very
  conversation back up rather than starting the ticket over;
- **nothing else is started**. The wait is written to
  `~/.local/state/ponos/ponos.db`, and the runs in between — a run is a process
  the timer starts, not a loop — find it and do nothing at all: no session, no claim, no
  answer in a thread. What was queued behind it is ticked the same way, rather than
  sitting in *ready* looking like a runner gone quiet;
- **the first run after it carries on**, and it takes the ticked tickets *first* — before
  anything else in *ready*. They are the ones already half done, and a board that spends
  the returning credit on starting things rather than on finishing them is a board that
  never finishes anything. Claiming one unticks it.

How long it waits is what Claude Code said. `Claude AI usage limit reached|1758031200` is
the CLI naming the moment; when it names none, the wait is a quarter of an hour and a run
that finds the limit still standing simply writes a new one. Guessing a full window would
be the expensive mistake — what was hit is the *end* of one, and it may be a minute away.

`ponos status` says how much of it is left, and the console says the same thing at
the top of *Live*, because a timer that is on above a board that does not move has only one
honest reading otherwise: it is broken.

The `Waiting for credit` checkbox is optional, like every property past the first few.
Being a property is what lets it reach a board that predates it at all: `ponos
init` adds it to a database it did not build, where an option on a real `status` cannot be
widened from outside Notion. Without it nothing breaks — the ticket goes back to *ready*
and the credit is waited out exactly as before, only with nothing on the board to say so.

Set `runner.wait_for_credits = false` to have the old behaviour back — an exhausted quota
reported as the session failure it looks like. There is one case for it: an
`ANTHROPIC_API_KEY` runner, which is billed per token and hits nothing to wait for.

### What a session may do alone

`[permissions]` is a policy every session reads — it is put in the prompt of every ticket
that works, a document ticket and a publication included — so that it stops asking the
same question twice. It has two lists of sentences, written in your own words and edited on
the *Execution* page of the Settings, where the defaults are shown and can be changed:

- `allowed` — what a session does without asking. By default: tag and publish a release of
  the project's repository after the merge into `main`; clone a missing repository of the
  project's GitHub owner, or of an owner `[github]` names, and create its Ponos project;
  re-run a CI; merge a validated pull request.
- `ask` — what always waits for your word, the ticket ending blocked with the question. By
  default: publishing on a public registry, opening a pull request or an issue on somebody
  else's repository, anything that sends a message to someone but you, deleting production
  data, changing a DNS, spending money.

A list the file does not carry is the default; a list written `[]` is an answer — nothing
allowed, or nothing held back. Two things hold whatever the lists say. A session that needs
a `sudo` password, an `npm login` or a code received by e-mail cannot be given one, so it
does not ask yes or no: it prepares the exact commands, ends blocked with the code
`access.sudo` or `access.credentials` (`CODE:` and one `COMMAND:` line each, next to the
other lines of the question) and the ticket starts again by itself when you answer « fait ».
And a ticket aimed at another repository than its project's — one of the project's GitHub
owner, or of an owner `[github]` names — is not a question when `allowed` lets the session
clone it: it creates the project and attaches the ticket there. An installation that already
wrote its own lists keeps them: nothing rewrites `config.toml`.

### Stopping before the wall

Waiting for a spent window is the cure; not spending it all is the treatment.
`runner.credit_reserve_percent` is the share of each window the runner refuses to touch —
5 by default, so it starts nothing past 95 % and there is still a subscription left for
the terminal *you* open.

It reads the same two figures Claude Code's own `/usage` shows — the session window and
the week — and takes the more constraining of them: 20 % of the week and 97 % of the
session is 97 % spent. Past the line:

- **nothing new is started**: not a ticket, not a publication, not an answer in a thread;
- **what is running is not killed** — it finishes. Stopping a session halfway to save
  credit would spend what it has already cost and get nothing for it;
- **everything that costs no credit carries on**: a pull request you validated this
  morning is still merged this afternoon, merged ones are still closed, the board is still
  swept. That is the whole difference between this line and a spent window, which stops
  the pass outright;
- **the tickets it did not start are ticked as waiting for credit** where they stand, and
  come back first when the window rolls over;
- **you are told once**, at the line and again on the way back — not on every pass. Four
  hours at a ten-second cadence is fourteen hundred passes, and a phone that rings on each
  of them is a phone that stops being read.

The reading is taken again at every free place rather than once a pass: a pass lasts as
long as its longest session, and the sessions in flight are what fills the window. `0`
spends the lot, which is what the runner did before this setting existed; `50` is the most
it will accept. If the usage cannot be read at all — no Claude Code store, a payload whose
shape changed — the runner says so once and behaves exactly as it does at `0`: a runner
that stopped working because it could not find a JSON key would be a far worse failure
than the one this guards against.

### Spending limits

`[budget]` draws three lines in dollars; empty is no limit, and both count what the CLI reports
a session cost — which a subscription does not, so they are for an API key or OpenRouter.

- **`budget.daily_usd`** is read where a session is about to *start*, against what the
  sessions started since local midnight cost — every one of them, those that name, classify
  or repair a ticket included, each written down the moment it ends. Past it nothing new begins — not a ticket, not
  a publication, not an answer in a thread — and what is running finishes. The ready tickets
  are ticked as waiting, Telegram and Slack are told once, and the console shows a banner;
  merges and everything else that costs nothing carry on. It lifts at midnight.
- **`budget.per_ticket_usd`** is handed to each session as `--max-budget-usd`: the CLI stops
  at the limit, between two steps, and the ticket goes to *blocked* with the reason. Answering
  it starts a new session, with a new allowance.

- **`budget.on_usd`** (one dollar when the line is absent; empty or `0` for none) is the same
  ceiling for one execution of a ticket's [`On` prompt](tickets.md#a-prompt-on-every-change-of-status).

The cost of a session that ended *blocked* or *failed* is written in the ticket's **Cost** like
any other — it was paid for all the same, and the daily limit counts it.
