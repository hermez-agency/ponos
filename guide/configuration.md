# Configuring Ponos

[The guide](README.md) · [Ponos](../README.md)

Notion, the configuration file, who answers the sessions, GitHub and the vault.

## Configuration

Everything lives in **`~/.config/ponos/config.toml`**, created by the installer
with mode `600` — everything but the secrets. `ponos config` opens it in
`$EDITOR`. The copies the console makes when it saves (`config.toml.bak`, and the scratch
copy it checks before swapping it in) are created `600` too, as are the console's token,
the session logs — under a `logs/` directory only your account can enter — and
`ponos.db`: each is created with that mode rather than tightened after the write, so
there is no moment in which the umask decides who reads them. What the runner keeps
between two runs — the history, the claims, the reconciliation stamps, the conversations —
is written in one SQLite transaction, and what is still a file (the channels' cursors) is
written to a copy and renamed over the old one, so a run killed mid-write leaves the old
state whole rather than an empty one.

**Secrets are not in `config.toml`, and are never read from it.** That file is one you
open, paste into a ticket, copy into an image or onto a shared volume — and a token goes
wherever it goes. They live in the environment, or in **`~/.config/ponos/secrets.env`**,
beside it (`PONOS_SECRETS` moves it): one `NAME=value` a line, the shape a shell's
`source`, compose's `env_file` and systemd's `EnvironmentFile` all read, created `600`. It
is the file the installer, `ponos init` and the console's Settings write a secret to.

| Variable | What it is | Where it used to be |
|---|---|---|
| `PONOS_NOTION_TOKEN` | the Notion integration token | `[notion] token` |
| `PONOS_WEB_TOKEN` | the console's token | `[web] token` |
| `PONOS_WEB_PASSWORD` | the console's sign-in password | `[web] password` |
| `PONOS_TELEGRAM_TOKEN` | the Telegram bot token | `[notify.telegram] token` |
| `PONOS_SLACK_TOKEN` | the Slack bot token (`xoxb-…`) | `[notify.slack] token` |
| `ANTHROPIC_API_KEY` | the key of the `api_key` provider | `[claude] api_key` |
| `OPENROUTER_API_KEY` | the OpenRouter key | `[openrouter] key` |
| `PONOS_GITHUB_TOKEN` | the GitHub token of `[github_access]` | `[github_access] token` |

When both have one, `secrets.env` wins — it is where the key you have just typed in the
console went, and it must not lose to one a compose file was started with weeks ago —
except for the console's password, where the environment wins: that is how a unit file or a
container claims a console before anybody opens it. A secret an older version left in
`config.toml` is ignored; the next launch moves it into `secrets.env` (and out of
`config.toml.bak`) and says so on stderr, or says, at every launch, which variable to set
when it cannot. `ponos doctor` checks that neither file gives a secret away.

**The file is checked as it is read.** Each table has its model (`src/ponos/schema.py`,
pydantic): what a key may hold, its default, and the rules the runner always applied — a
value under a key's floor is the floor (`interval_seconds = 0` is one second), a word that
is none of a key's choices is the default (a typo in `update_channel` is `release`, never
`main`), an amount left blank is no limit, and a key nobody reads is left alone. A value
none of that reads — a port that is not a number, a list where a word goes — stops the
runner, the console's save and `ponos doctor` with the key and its line:

```text
✗ /home/you/.config/ponos/config.toml, line 12: web.port = 'eighty' — Input should be a valid integer, unable to parse string as an integer
```

`config.example.toml` is read against these models by the tests, and documents every key
they read — no more, no fewer.

Steps 1 to 3 are for a board in Notion. A board of Markdown files needs none of them —
one line, under [Without Notion](board.md#without-notion-the-board-as-markdown-files) — and goes
straight to step 4.

### 1. Create a Notion integration

The runner works alone, on your machine, at three in the morning. It needs an identity of
its own: an **internal integration**, which is a robot account with its own token.

On [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New
integration** → give it a name (`Ponos`), pick your workspace, type **Internal**.
Copy the token it shows you; it starts with `ntn_`.

### 2. Share one page with it

Open any Notion page — an empty one will do — and share it: the `···` menu, top right →
**Connections** → your integration. That click is the floor: an integration cannot grant
itself access, so it is the one step no command can take for you.

### 3. Let the runner build the rest

```sh
ponos init https://www.notion.so/your-page --token ntn_…
```

It creates everything under that page and writes the result into your configuration —
the token into `secrets.env`, the workspace into `config.toml`:

```
your page                 ← the one you shared
└── ponos         ← the workspace: its rows are the master pages
    ├── Tickets           ← the tickets database, 12 columns, 2 relations
    ├── Projects          ← Name, Repository, Path
    ├── Agents            ← the roles a ticket can be handled by
    └── Context           ← a plain page: who you are
```

Plus a demonstration ticket, left unstarted, so the first thing you do is move something
to *Ready* and watch it work.

**Running it again is safe** — and is how you upgrade. Nothing is duplicated: what exists
is kept, what a previous version did not know how to create is added, and a column you
retyped on purpose is never overruled.

> One Notion quirk shows through: the API cannot create a `status` property, so `Status`
> is made a **select** with the same five options. The runner reads either — it looks at
> the declared type and writes accordingly — so this changes nothing but the icon.

You name the directory once; the runner finds the rest by the **title of a row**. Rename
a row and tell the runner what it is now called, under `[notion.pages]`:

```toml
[notion.pages]
tickets = "Tickets"     # required
projects = "Projects"   # optional — only `doctor` uses it
agents = "Agents"       # optional — see below
context = "Context"     # optional — see below
```

Rows created under the names this shipped with before — `Master Tickets`, `Soul` — are
still found as long as this table does not name them otherwise. There is nothing to
rename on an existing board.

If you would rather point at one database than share a whole workspace, `tickets_database`
still works exactly as before, and wins over the workspace when both are set. The URL of
the database is enough, and if it is inline inside a page, the page URL works too: the
runner looks inside and finds the database on its own.

Three ways to get them in, whichever you prefer:

```sh
ponos config      # opens the TOML in your editor — the cleanest

# or let the installer ask you (it does, on a fresh install):
curl -LsSf https://raw.githubusercontent.com/hermez-agency/ponos/main/install.sh | sh

# or in one line — the token goes beside the file, never in it:
echo 'PONOS_NOTION_TOKEN=ntn_…' >> ~/.config/ponos/secrets.env && chmod 600 ~/.config/ponos/secrets.env
```

### The step everyone forgets

A valid token on a page that was never shared answers `object not found`, and nothing
about it hints at why — which is why step 2 is the sharing. Everything created underneath
inherits that access in one gesture, and that is also what makes the relations legal: a
relation can only point at a database the same integration can reach.

> **What you share is what the runner can read.** Anything under that page reaches the
> prompts it writes, and prompts are kept on disk in `~/.local/state/ponos/`. Keep
> credentials out of the workspace — a page of environment variables is exactly the kind
> of thing that should live in a password manager instead.

Then:

```sh
ponos doctor
```

which checks the token, the access to the database, the type of every column and the
presence of each status — and names whichever of those was missed.

The console's dashboard says the same thing without a terminal: an "Installation status"
band lists what is misconfigured — Notion, GitHub, Claude Code, each project, the machine —
with its probable cause, and either a **Configure** button (a missing property or status
on the Notion board, a project's default branch: Ponos changes it only after you confirm)
or the exact steps and the link to follow. It checks again when the page opens and on
**Recheck**, and it is not drawn while everything is green. `ponos doctor` prints the same
checks (`src/ponos/health.py`) — every one of them, `doctor` asks nothing on its own —
grouped as the band groups them (*Board*, *GitHub*, *Claude*, *Projects*, *Machine*,
*Settings*), with the settings it only describes in grey, which the band leaves out. The one
thing the two do differently: `doctor` asks the remote for the newest version, the dashboard
reads what the last check found.

### 4. The rest of the file

Every key below is also a field in the console's **Settings** tab —
`ponos serve`, and the same file, drawn as a page. What follows is the same list,
for reading rather than for filling in.

| Key | Default | Effect |
| --- | --- | --- |
| `runner.workspace_root` | `~/workspace` | where to look for repositories — and where one you have not cloned yet is cloned |
| `runner.interval_seconds` | `1800` | seconds between two passes, and how often a pass in flight looks at the board — for a ticket to put in an empty place, and for one you have validated since — `ponos enable` applies a change |
| `runner.max_concurrent` | `2` | tickets handled side by side — an empty place is filled from the board without waiting for anything to end |
| `runner.max_concurrent_per_project` | `2` | of those places, how many one project (with a repository) may hold at once — the next ticket of another project goes first, and the held one starts when a place of its project frees |
| `runner.timeout_minutes` | `30` | past this, the session is killed and the ticket fails |
| `runner.wait_for_credits` | `true` | a spent subscription window puts the runner to sleep instead of failing tickets — see [When the credits run out](credits.md#when-the-credits-run-out) |
| `runner.credit_reserve_percent` | `5` | the share of each window the runner refuses to touch, so there is a subscription left for you — `0`–`50`, see [Stopping before the wall](credits.md#stopping-before-the-wall) |
| `runner.model` | `""` | `"opus"`, `"sonnet"`… empty = the CLI's default |
| `runner.language` | `""` | `"fr"` to be answered in French — see [The language it answers in](board.md#the-language-it-answers-in) |
| `runner.app_language` | `""` | the language the console opens in; empty follows `runner.language` — see [The language it answers in](board.md#the-language-it-answers-in) |
| `runner.permission_mode` | `"bypassPermissions"` | see [What protects your code](safety.md#what-protects-your-code) |
| `runner.branch_prefix` | `"ticket/"` | prefix of the created branches |
| `runner.base_branch` | `""` | empty = each repository's default branch |
| `runner.push` | `true` | `false`: commits stay local |
| `runner.open_pull_request` | `true` | `false`: the branch is pushed, without a PR |
| `runner.rebase` | `true` | replay the branch onto its base before the pull request, and once more when a validated merge is refused for being behind |
| `runner.resolve_conflicts` | `true` | when that replay stops on a conflict, a session resolves it, checks it, and the merge is asked again |
| `runner.resolve_conflicts_except` | `""` | projects, by name and comma-separated, whose conflicts are always left to you |
| `runner.resolve_model` | `""` | the model that resolves — empty: the ticket's own |
| `runner.checks_timeout_minutes` | `20` | how long a resolved pull request's CI is waited for before the merge; `0` does not wait |
| `runner.local_ci` | `false` | run the project's CI on this machine, in Docker, once the session has committed and before the push — the command the project's Settings tab declares, else its workflows through `act`; a red one goes back to the same session to be fixed. Needs Docker; a project may say otherwise for itself. GitHub's CI still runs |
| `runner.local_ci_attempts` | `3` | how many times the local CI runs, the first included; still red after the last, the ticket is blocked (`merge.local-ci-failed`) and no pull request is opened |
| `runner.local_ci_concurrent` | `1` | how many local CIs run at once on this machine; the next waits for a place. Containers, networks and compose volumes are named `ponos-ci-<ticket>` and removed after each run |
| `runner.merge_method` | `"squash"` | how a **validated** pull request is merged — `squash`, `merge`, `rebase` |
| `runner.force_validated_code` | `false` | merge a Code ticket's pull request as soon as its session succeeds, then *Done* — see [*Force validated*](tickets.md#force-validated-skipping-the-review) |
| `runner.force_validated_publication` | `false` | publish a Publication as soon as it is prepared, without waiting in review |
| `runner.force_validated_writing`, `runner.force_validated_external` | `false` | the same switch for Writing and External action — which already end in *Done*, so they change nothing today |
| `runner.relaunch_delay_seconds` | `15` | a session killed from outside (SIGKILL/SIGTERM, or cut by a network outage) is resumed once after this delay if the network answers; killed again, the ticket is blocked as `session.killed` with the exact reason |
| `runner.min_free_memory_mb` | `2048` | no session is started while less memory than this is available (`MemAvailable`); `0` turns the guard off. `ponos doctor` reports it |
| `runner.keep_worktree_on_failure` | `true` | keep enough around to understand a failure |
| `runner.notify` | `true` | one desktop notification per finished ticket, clicked to open its Notion page — `[notify]` carries it to your phone |
| `runner.auto_update` | `true` | a run keeps the installation on the latest version |
| `runner.update_channel` | `"release"` | what "latest" means: the newest `vX.Y.Z` tag, or `"main"` for every commit. No tag, no update; anything unknown reads as `"release"` |
| `runner.update_interval_seconds` | `3600` | how often a run asks; one minute is the floor |
| `runner.log_retention_days` | `14` | drop older session logs, once a day; `0` keeps everything |
| `runner.min_free_disk_mb` | `5120` | under this much free disk (in MB), a tidy runs before any ticket is started; if the space is still short, nothing starts, the ticket stays in Ready and the console says so; `0` turns the guard off. `ponos doctor` reports it |
| `runner.stale_worktree_days` | `30` | once a day, remove any worktree untouched for this long, whatever its ticket — never one whose ticket is in progress, nor one with uncommitted changes or commits no remote has; its local branch goes when a remote holds all of it; `0` turns it off |
| `runner.worktree_exclude` | `""` | folders new worktrees are made without (sparse checkout), e.g. `"docs/media"` — left out before the checkout so big media never reach the disk; a ticket that needs one runs `git sparse-checkout disable` |
| `runner.clean_done_worktrees` | `true` | once a day, also remove the worktrees and scratch directories of tickets done or cancelled for `log_retention_days` — see [What `clean` removes](usage.md#what-clean-removes-and-what-it-refuses-to) |
| `runner.attach_sessions` | `true` | file each session under its project, so `claude --resume` there lists it |
| `runner.prompt_file` | `""` | your own prompt template, for repository tickets |
| `runner.document_prompt_file` | `""` | the same, for tickets with no repository |
| `runner.delivery_prompt_file` | `""` | the same, for publishing a validated ticket |
| `runner.classify` | `true` | work out the type of a ticket that reaches *Ready* with none — `false` runs it by its project, as before. See [The type of a ticket](board.md#the-type-of-a-ticket) |
| `runner.classify_model` | `"haiku"` | the model that classifies: it reads one page and answers one line. Empty is the CLI's own |
| `runner.auto_model` | `true` | choose the model of a ticket whose `Model` is empty, from its type, size, wording and priority — `false` gives every one `runner.model`. See [The model of a ticket](board.md#the-model-of-a-ticket) |
| `runner.auto_model_light` … `auto_model_heaviest` | `"haiku"`, `"sonnet"`, `"opus"`, `"fable"` | the model of each of the four levels; an empty one borrows the nearest |
| `runner.auto_model_code` … `auto_model_publication` | `"standard"`, Writing `"light"` | the level each type starts from: `light`, `standard`, `heavy` or `heaviest` |
| `runner.auto_model_subtype_bug` … `auto_model_subtype_security` | Docs and Chore `"lower"`, Sécurité `"higher"`, the others `"same"` | how a code ticket's sub-type moves the level Code starts from: `lower`, `same` or `higher` |
| `runner.auto_model_escalate` | `true` | a ticket whose chosen model failed runs one level up next time, once |
| `runner.use_fable` | `false` | allow Claude Fable at all; off, every session the runner starts — chosen, escalated, written on a ticket or its agent, the console's chat — runs on `opus` instead |
| `runner.classify_confidence` | `"medium"` | `low`, `medium` or `high` — the least confidence a guess is acted on with; below it, the ticket is blocked with the question |
| `storage.mode` | `"notion"` | which board answers — `notion`, `markdown`, or `both` kept in step. See [Without Notion: the board as Markdown files](board.md#without-notion-the-board-as-markdown-files) |
| `storage.path` | `~/.local/state/ponos/board` | the directory the Markdown board lives in |
| `storage.conflict` | `"newest"` | in `both`, who wins when the same page moved on each side |
| `storage.on_every_pass` | `true` | in `both`, reconcile before each pass — `false` leaves it to `ponos sync` |
| `notion.workspace` | `""` | the database whose rows are your master pages |
| `notion.tickets_database` | `""` | one database instead of a workspace; wins when both are set |
| `[notion.pages]` | | which row of the workspace is the tickets database, the projects database, the agents database, the context page |
| `[notion.properties]` | | if your columns have other names |
| `[notion.status]` | | if your statuses have other names |
| `[notion.types]` | | how the options of the Type column are spelled — `code`, `writing`, `external`, `publication`. Unset, the French *Rédaction* and *Action externe* are read too |
| `[projects]` | | `"Notion name" = "/path"` for repositories that cannot be guessed |
| `[github]` | | `"owner" = "gh account"`, when this machine answers to more than one GitHub — see *Several GitHub accounts* below |
| `[web]` | | the console's host, port, and how it is opened — a token, or an email and a password. See *The web console* |
| `web.attachment_max_mb` | `25` | how heavy a file sent to the workspace may be |
| `web.attachment_days` | `7` | how long a conversation's files are kept when nobody starts a new one |
| `web.send_after_transcription` | `false` | send a dictated message as soon as it is transcribed, rather than leave it to be read over |
| `OPENROUTER_API_KEY` | | not a key of this file: the secret is in `secrets.env` or the environment (see the secrets above) — one key in front of every other provider, see *Every other model* below |
| `openrouter.route_sessions` | `false` | run the sessions themselves on it |
| `openrouter.base_url` | `https://openrouter.ai/api/v1` | only for a gateway of your own |
| `openrouter.transcription_model` | `openai/whisper-1` | what the console's microphone is transcribed with |

`max_concurrent_per_project` caps how many of those places one project may hold: pull
requests written side by side on one repository touch the same files, and each one that
lands makes the others conflict. A ready ticket whose project is already at the limit stays
in the column — the pass says `project at its limit` — and the next ticket of another
project goes first; it starts as soon as a ticket of its project ends. Projects without a
repository (documents) are not counted. It is also in the console's *Settings*, under
*Tickets in parallel per project*.

`max_concurrent` is a number of **places**, not a batch size. A pass keeps that many
sessions running for as long as the ready column has anything in it: a session that ends
frees a place, the board is read again on the spot, and what goes in is whichever ticket
is top of the queue *then* — highest priority score, date, age, exactly as at the start. So a ticket
made ready at 14:10 starts at 14:10 rather than waiting on the two-hour session that
began at 14:04, and the pass ends when nothing is ready and nothing is in flight.

A place does not have to be *freed* to be filled: one that was never taken — two places,
one ticket ready — is looked at too, every `interval_seconds`, for as long as the pass
lasts. That is the same cadence the timer reads the board on, and it has to come from the
pass, because the run lock belongs to the pass until it ends and the timer only meets it
and leaves. Without it, tickets arriving one at a time would run one at a time whatever
`max_concurrent` said, which is exactly what a board with one ticket in progress and
three waiting looks like.

The *validated* column is read on that same cadence, and even when every place is taken:
a merge needs no place — it is two `gh` calls in the pass's own thread — and a
publication takes the next one that frees, before any ready ticket. Work you have
accepted is one gesture from done, and nothing about a session in flight has anything to
do with it. See [Validated, and what it sets off](tickets.md#validated-and-what-it-sets-off).

A ticket moved back to ready is asked for again, whether or not this pass already ran
it: it is held out only while a session of the pass is still on it — and fifteen seconds
after, for Notion to stop serving its old status — then played again on its branch and
its pull request, with a new report on the ticket. A ready card in the console always
says what it is waiting for: its date, the credit, the reserve or the day's limit, a
session still on it, every place taken, the next reading of the board, or a timer that
is off. The pass writes the same reasons in its log as they change, starting with `…`.

Two things follow. `ponos run --limit 3` means three tickets for that pass, not
three at a time — the limit caps what is taken off the ready column, `max_concurrent`
caps what runs at once, and a validated ticket carried out along the way is counted by
neither. And a comment addressed to the runner during a long pass is answered by the
**next** pass, because answering starts a session of its own and that would put more
sessions in flight than you allowed. An answer to a *blocked* ticket asks for work rather
than for a reply, so that one is picked up by the pass itself at the next freed place —
including one typed in Telegram or Slack, which is written onto its ticket at every
refill.

### Who answers the sessions

Every session the runner starts is Claude Code, and Claude Code has to be paid for by
somebody. On a laptop that was never a question — `claude` was signed in once, and that
was the subscription. On a server it is the first one, and `[claude]` is where it is
answered:

```toml
[claude]
provider = "cli"        # or "api_key", or "openrouter"
```

| `provider` | What it is | What goes with it |
|---|---|---|
| `"cli"` | Claude Code signed in as you, `claude auth login` once on that machine | Your subscription. The only one that keeps **Claude in Chrome**, and the only one whose credits come in windows worth [waiting for](credits.md#when-the-credits-run-out). |
| `"api_key"` | An Anthropic key: `ANTHROPIC_API_KEY`, in `secrets.env` or the environment | Billed by the token. No browser, nothing to wait for. |
| `"openrouter"` | The OpenRouter key (below), `OPENROUTER_API_KEY` | With `route_sessions = true` the sessions run there, and a model is an OpenRouter slug. No browser, nothing to wait for. |

An empty `provider` is a file written before the key existed, and it reads the way that
file always worked: OpenRouter when its sessions are routed there, the CLI otherwise. A key
in the file wins over the one in the environment, which only fills an empty line — a key
somebody has just typed and checked must not lose to one a compose file was started with.
An Anthropic key is handed to a session only when it is the provider: given to a CLI
session, it would quietly take the place of the subscription.

In the console the key is **Settings › Models and costs › Provider and default model ›
Anthropic API key**, with the provider just above it — choose *Anthropic API key* there, or the
sessions keep running on the CLI. The key is written to `secrets.env`, never to
`config.toml`, and never comes back to the browser: the field says *set · ends …abcd*,
typing a new one replaces it, and **Forget** removes it. **Test the connection** asks Anthropic whether
the key works — the one just typed, or with an empty field the one the runner uses — and
saves nothing. On a server, `ANTHROPIC_API_KEY` in the environment (a Dokploy variable)
does the same job; the page says when the environment is where the key comes from.

The [first connection](console.md#the-first-connection) asks this in its second step and tries the
key before writing it; `ponos doctor` says which provider is in use, where the choice
came from, and — for the CLI — whether `claude auth status` finds an account signed in.

### Every other model

What the runner drives is Claude Code, and Claude Code talks to Anthropic: one family of
models, on one subscription. An [OpenRouter](https://openrouter.ai/keys) key is one account
in front of every provider there is, and it reaches a session two ways.

```sh
# ~/.config/ponos/secrets.env — or the environment
OPENROUTER_API_KEY=sk-or-v1-...
```

That alone changes nothing about the runner. The key is simply *there*, in the environment
of every session it starts, as `OPENROUTER_API_KEY` — the name every library and every
snippet already looks for. So a ticket can have a GPT write the copy, a model transcribe an
audio file or another make the video, and pay for it, without the runner having to know
what any of those are.

The other way is a decision rather than a convenience:

```toml
route_sessions = true
```

The sessions themselves then run on it. Claude Code speaks to OpenRouter instead of to
Anthropic, and every model named — a ticket's **Model** column, an agent's, `runner.model`
— becomes an OpenRouter slug rather than `"opus"`:

```toml
model = "openai/gpt-5"     # or "anthropic/claude-sonnet-4.5", or anything on the list
```

Two things travel with that, and neither is a detail. The CLI is then authenticated by a
token instead of as you, so **Claude in Chrome does not load** — a ticket that needed the
browser cannot be handled that way. And the bill is OpenRouter's rather than the
subscription's: nothing is metered in windows any more, so `runner.wait_for_credits` has
nothing left to wait for, and `runner.credit_reserve_percent` no window to reserve a share
of.

Both switches are fields of the console's **Settings** tab, under *OpenRouter (other models)*; the
key is a secret like any other, so it goes out to the page as “set, ending in …abcd” and
comes back only when you type a new one.

The key has one use inside the runner itself: **the console's microphone**. Claude Code
reads no audio, so a message dictated in the console is transcribed by
`openrouter.transcription_model` (`openai/whisper-1` by default) before it is a message at
all. Without a key, the microphone is greyed out and says why.

### Connect GitHub in one click

`gh auth login` is a step somebody types on the machine, a token tied to their own
account, and one that sees every repository they can. The console has a shorter road:
**Settings › GitHub › Connect GitHub** (also a step of the first connection). One click,
and Ponos has its own GitHub App, installed on the repositories you choose — nothing to
copy, no token to paste.

1. The console posts a **manifest** to GitHub — the app already described: named
   *Ponos — {this machine}*, private, with the repository permissions a code ticket needs
   (contents, pull requests and workflows to write; metadata, checks, statuses, actions and
   issues to read), no organisation permission and no webhook. Give an **organisation** in
   the field beside the button to create it there (you have to be one of its owners);
   empty, it is your personal account.
2. GitHub shows *Create GitHub App*. Accept, and it sends you back to the console with a
   code, which the console exchanges for the app's credentials — once, within the hour,
   and only with the `state` it sent out, which is good once and for an hour too.
3. The console goes straight on to the app's installation page: pick the repositories.
4. GitHub sends you back to **Settings › GitHub**, which says *GitHub connected*, as which
   app, on which account, and lists the repositories it reaches. *Add repositories* leads
   back to the installation page; *Disconnect* deletes the credentials from this machine
   and says where to delete the app on GitHub.

The browser has to reach the console for the two ways back — `localhost` is enough, the
redirections happen in your browser. The console uses the address you reached it by, or
`web.url` when you came through it.

From then on, every repository whose owner the app is installed on is worked **as the
app**: the clone, the push and the pull request go out with an installation token, and the
pull requests and the commits are signed `{app}[bot]`. The token lasts an hour and is
renewed ten minutes before it lapses; a session that runs longer is given a credential
helper and a `gh` that fetch a new one themselves. The token is handed to `git` through
its environment — never written into `.git/config` — and to `gh` and the sessions as
`GH_TOKEN`, so every tool that already speaks `gh` keeps working. The app's key and its
tokens are never shown, in the console, the logs or a ticket: the credentials are one line
of `secrets.env` (`PONOS_GITHUB_APPS`), 0600 like the other secrets.

A private app is installed on the account that owns it alone: your own repositories and an
organisation's are **two apps**, connected one after the other (*Connect another account*).
Each repository is worked by the one installed on its owner. An owner no app is installed
on — and a machine with no app at all — is worked through `gh` exactly as before, and so is
everything when GitHub does not answer. `ponos doctor` says which apps are connected,
whether each one still gets a token, and which repositories of the workspace no app reaches.

### Or an access token

A GitHub App is the right shape for a robot, and a lot to set up for a first ticket. A
**fine-grained personal access token** does the same work in a paste. In **Settings ›
GitHub** (and in the first connection's GitHub step), *Create a fine-grained token on
GitHub* opens GitHub's form with the permissions already filled in: **Contents** and
**Pull requests** on read and write, **Metadata** on read-only (and Workflows, Actions,
Checks, Statuses and Issues for the tickets that touch a workflow or read a failed check).
Pick the repositories tickets may work on under *Repository access*, paste the token, and
the console **checks it before keeping it**: who it belongs to, which repositories it
reaches and which of them it may write to, and whether pull requests answer. A token GitHub
refuses (mistyped, expired, revoked) or that lacks a permission is not kept, and the answer
names the permission — *Missing: Pull requests — Read and write*. Writing a pull request
cannot be tried without opening one, so that is said, not guessed.

Prefer the **App** for an organisation, for several people, or when you want tokens that
expire on their own — an installation token lasts an hour, a personal one lasts as long as
you made it. The token suits one person and a first try.

- **Where it is kept.** Never in `config.toml`, a ticket or a log: it is `PONOS_GITHUB_TOKEN`
  in `secrets.env` (0600, what the console writes), or in the environment — which is how a
  container or Dokploy is given it — or an item of the vault you already use, with
  `[github_access] token_item = "pass:ponos/github"` (`keyring:…`, `bitwarden:…`; see *Keys a ticket may use: the vault*). Every value read is masked wherever the runner
  writes.
- **Who answers.** `[github_access] mode` is `"app"` or `"token"` to put that one first
  (also *Settings › Code › GitHub access*; pasting a token in the console selects it). Empty,
  the App answers for the owners it is installed on, then the token, then the `[github]`
  accounts and `gh`.
- **One door.** The clone, the push, the pull request, its comments and the merge all go out
  with the token through `GH_TOKEN` and git's environment — as they do with the App, only
  the token differs. The session is handed it too, and commits are signed as usual.
- `ponos doctor` has a *GitHub token* line under *GitHub*: where it comes from, who it is, what it lacks.

### Several GitHub accounts

Without the app, and for the owners it is not installed on: one machine often answers to
two GitHubs — your own and a client's — and `gh` only ever has **one of them active**. Everything the runner asks it about a repository the other
account owns is then refused for reasons that read like a bug: a pull request that cannot
be created, a repository GitHub says does not exist, a merge nobody is allowed to make.

Log each account in once — they stay signed in side by side — and say which owner is
whose:

```sh
gh auth login      # then again, for the second account
gh auth status     # lists what it knows
```

```toml
[github]
"northwind" = "dev-northwind"        # the owner in the URL = the gh account
"hermez-agency" = "hermez-bot"
```

On the left the **owner**, as GitHub spells it in a repository's URL; on the right the
**account**, as `gh auth status` lists it. Everything that leaves the machine about a
repository — the clone, the push, the pull request, the merge, the question “has this been
merged yet?” — then goes out under the account its owner names here, whichever account
`gh` happens to be active as. The token never touches the configuration file: it is asked
of `gh` when it is needed, and lives in your keyring as before.

An owner this table does not name is worked under whichever account `gh` is signed in as,
which is what one GitHub has always done — so a machine with one account leaves this out
entirely. A line naming an account `gh` is *not* signed in as is not a ticket's problem
either: the command runs as the active account, and `ponos doctor` is what says
the line is dead. The table is also a section of the console's **Settings** tab, *GitHub
accounts*.

### Keys a ticket may use: the vault

A ticket that publishes a package, redeploys a service or calls an API needs a token — and
a ticket is the worst place to write one: it is a Notion page, a prompt, a transcript and
sometimes a pull request. So keys stay where they already live, and `[vault]` says two
things: **where** they are read, and **which ones each project is given**.

```toml
[vault]
provider = "pass"                 # env, keyring, pass or bitwarden

[vault.projects.Ponos]            # the project's exact Notion name
NPM_TOKEN = "hermez-agency/npm"   # the variable the session sees = the item it is read from
GH_DEPLOY_TOKEN = "keyring:ponos-deploy"   # one key that lives somewhere else

[vault.projects]
Leadz = ["LEADZ_DOKPLOY_TOKEN"]   # a list: each one read under its own name
```

| `provider` | Reads | What it needs |
| --- | --- | --- |
| `env` (default) | the runner's environment, then `secrets.env` beside `config.toml` | nothing |
| `keyring` | the GNOME keyring, or any Secret Service, through `secret-tool lookup` — a bare name is `service ponos username <name>`; `attr=value attr=value` finds any other item | `libsecret-tools`, and a keyring unlocked by your session |
| `pass` | the first line of `pass show <item>` | `pass`, and a `gpg-agent` that has the passphrase |
| `bitwarden` | `bw get password <item>`, by name or id | the Bitwarden CLI, unlocked: `BW_SESSION` in the environment or in `secrets.env` (`bw unlock --raw`) |

Those keys reach the sessions of **that project's tickets, and nobody else's**, as
environment variables. The prompt tells the session their names — never their values —
and asks it to use them as `$NPM_TOKEN` and never print them. A project the table does not
name is given nothing; the runner's own variables (`PONOS_*`, `ANTHROPIC_API_KEY`, the
OpenRouter key) are never handed to a project, and win over a key of the same name. Each
key is read again at every session, so a token rotated in the keyring is the one the next
ticket gets; one that cannot be read is said in the log, by name, and the ticket runs
without it.

And a value read is a value **masked**. A session may still print its key — an `env` to
debug a deploy, a verbose `npm publish` — so every value read is replaced by `***` before
anything goes out: the comments and pages written to Notion or to the Markdown board, the
session's transcript and stderr, the runner's log, Telegram and Slack, the console's
answers. By value, not by name: what leaks is never `$NPM_TOKEN`, it is what it expands
to. A value under six characters is too short to mask without masking the code around it,
and is not handed over at all.

**Prefer keys of narrow reach.** An npm *granular* token limited to the packages and the
organisation it publishes, a GitHub *fine-grained* token limited to one repository and the
permissions it needs, a Dokploy key for one project — never a password, and never a
token that can do everything your account can.

**Adding one — hermez-agency's npm token, for the Ponos project:**

1. On npmjs.com, *Access Tokens › Generate New Token › Granular Access Token*: read and
   write on the `hermez-agency` organisation's packages only, with an expiry.
2. Put it in the vault, without it ever touching a shell history:

   ```sh
   pass insert hermez-agency/npm
   # or, in the GNOME keyring:
   secret-tool store --label="Ponos · hermez-agency npm" service ponos username hermez-agency-npm
   # or, with no vault at all, a line of ~/.config/ponos/secrets.env (kept 0600):
   #   NPM_TOKEN=npm_…
   ```

3. Grant it to the project, in `~/.config/ponos/config.toml`:

   ```toml
   [vault]
   provider = "pass"

   [vault.projects.Ponos]
   NPM_TOKEN = "hermez-agency/npm"      # or "keyring:hermez-agency-npm", or "env:NPM_TOKEN"
   ```

4. `ponos doctor` reads it, and answers `✓ Vault: Ponos is given NPM_TOKEN.` — or why it could not. A
   ticket of Ponos can then publish with `NPM_TOKEN` in its environment (an `.npmrc` that
   says `//registry.npmjs.org/:_authToken=${NPM_TOKEN}`). Publishing on a public registry
   is still one of the actions it asks before, whatever key it holds.

Another provider — 1Password's `op read`, say — is one class in `src/ponos/vault.py` with a
`read(item)` and an `available()`, and one line in its `PROVIDERS`.
