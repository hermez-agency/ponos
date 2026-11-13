# Configuring Ponos

[The guide](README.md) · [Ponos](../README.md)

The configuration file, who answers the sessions, GitHub and the vault.

## Configuration

Everything lives in **`~/.config/ponos/config.toml`**, created by the installer
with mode `600` — everything but the secrets. `ponos config` opens it in
`$EDITOR` — once it has converted a file an older version wrote, see
[*A file from an older version*](#a-file-from-an-older-version-ponos-config). The copies the console makes when it saves (`config.toml.bak`, and the scratch
copy it checks before swapping it in) are created `600` too, as are the console's token,
the session logs — under a `logs/` directory only your account can enter —, the files
attached in the console's chat and `ponos.db`: each is created with that mode rather than
tightened after the write, so there is no moment in which the umask decides who reads them.
The state directory itself (`~/.local/state/ponos`, `/data/state/ponos` in the image) and
the folders at its top are closed (`700`) at each launch; `ponos doctor` reports what is
still readable by other accounts under it — outside the worktrees, clones of your
repositories — and the console's health band offers to tighten it. What the runner keeps
between two runs — the history, the claims, the reconciliation stamps, the conversations —
is written in one SQLite transaction, and what is still a file (the channels' cursors) is
written to a copy and renamed over the old one, so a run killed mid-write leaves the old
state whole rather than an empty one.

**Secrets are not in `config.toml`, and are never read from it.** That file is one you
open, paste into a ticket, copy into an image or onto a shared volume — and a token goes
wherever it goes. They live in **Ponos's vault** — `~/.local/state/ponos/vault.db`, where
each one is sealed with AES-256-GCM, the vault of [Context → Vault](#ponoss-own-vault-context--vault) —
or in the environment. The console's Settings and its first connection write a secret into
the vault, and nowhere else; it stays apart from the vault's entries, so no project can be
granted one and no session is ever handed it. Without the vault's key (the keyring,
`PONOS_VAULT_KEY` or `~/.config/ponos/vault.key`) Ponos still starts, with the environment's
secrets only, and `ponos doctor` says why the vault does not open.

| Variable | What it is | Where it used to be |
|---|---|---|
| `PONOS_WEB_TOKEN` | the console's token | `[web] token` |
| `PONOS_WEB_PASSWORD` | the console's sign-in password | `[web] password` |
| `PONOS_TELEGRAM_TOKEN` | the Telegram bot token | `[notify.telegram] token` |
| `PONOS_SLACK_TOKEN` | the Slack bot token (`xoxb-…`) | `[notify.slack] token` |
| `ANTHROPIC_API_KEY` | the key of the `api_key` provider | `[claude] api_key` |
| `OPENROUTER_API_KEY` | the OpenRouter key | `[openrouter] key` |
| `PONOS_GITHUB_TOKEN` | the GitHub token of `[github_access]` | `[github_access] token` |

When both have one, the vault wins — it is where the key you have just typed in the
console went, and it must not lose to one a compose file was started with weeks ago —
except for the console's password, where the environment wins: that is how a unit file or a
container claims a console before anybody opens it. The environment stays a source of its
own: it is how [Docker](server.md#docker) and the Dokploy template hand a server its
secrets.

A secret an older version left in `config.toml` is ignored; the next launch moves it into
the vault (and out of `config.toml.bak`) and says so on stderr, or says, at every launch,
which variable to set when it cannot. So does a **`secrets.env`** from before the vault —
the `NAME=value` file beside `config.toml` where the secrets used to be kept in clear: the
next launch seals every line of it in the vault, those [`[vault]`](#keys-a-ticket-may-use-the-vault)'s
`env` provider reads included, and deletes the file. Nothing reads it any more, nor
`PONOS_SECRETS`. A name the vault already holds is not overwritten. `ponos doctor` checks
that neither file still holds a secret.

**The file is checked as it is read.** Each table has its model (`src/ponos/schema.py`,
pydantic): what a key may hold, its default, and the rules the runner always applied — a
value under a key's floor is the floor (`interval_seconds = 0` is one second), a word that
is none of a key's choices is the default (a typo in `update_channel` is `release`, never
`main`), and an amount left blank is no limit. A value none of that reads — a port that is
not a number, a list where a word goes — stops the runner, the console's save and
`ponos doctor` with the key and its line:

```text
✗ /home/you/.config/ponos/config.toml, line 12: web.port = 'eighty' — Input should be a valid integer, unable to parse string as an integer
```

So does a key, or a table, that no model reads: a misspelt key is a setting that does
nothing while looking like one. The line names it, and the known one it is closest to:

```text
✗ /home/you/.config/ponos/config.toml, line 4: runner.max_concurent is not a key of config.toml (did you mean runner.max_concurrent?) — ponos config converts a file an older version wrote
```

The secrets an older version wrote in the file are not among them: those are moved, see above.

### A file from an older version: `ponos config`

The file came down to some thirty keys in four steps, and what left it is listed, key by
key, in the `CHANGELOG.md` entry of that version. A file written before is converted once,
by hand, with:

```sh
ponos config            # converts, says what moved — and opens the file when there was nothing to convert
ponos config --convert  # converts, and never opens an editor
```

It keeps the file as it was beside it (`config.toml.old.bak`), moves the secrets still in it
into Ponos's vault, each `[projects]` line into the *Repository path* of that project's
Settings tab and each `[vault.projects]` table into its *Vault keys* (what the project
already says wins), writes the four `force_validated_<type>` booleans as the one
`force_validated` list, and removes every retired key and table — `[notion]`,
`[openrouter]`, `[speech]`, `[browser]`, `[review]`, `[storage]` and `[issues]` included — with the comment block above
a table's header. Nothing is regenerated: the rest of the file, its comments included, stays
as you wrote it. A key it does not know to have been retired is left where it is — it may
be a misspelling of a real one — and the load names it. Run again, it finds nothing to do and
writes nothing. No launch converts on its own: until it is run, Ponos stops on the first
line it does not read.

`config.example.toml` is read against these models by the tests, and documents every key
they read — no more, no fewer.

### Checking it: `ponos doctor`

After a change:

```sh
ponos doctor
```

which checks the board, who answers the sessions, GitHub, each project, the machine and the
file itself — and names whichever of those is not in place.

The console's dashboard says the same thing without a terminal: an "Installation status"
band lists what is misconfigured — the board, GitHub, Claude Code, each project, the machine —
with its probable cause, and either a **Configure** button (a project's default branch, the
state directory's permissions: Ponos changes it only after you confirm)
or the exact steps and the link to follow. The checks take a few seconds — `gh` asks
GitHub, the board and every project are read — so the page shows what they found up to
five minutes ago. Past that, the page still opens at once on the last answer, and the
checks run again behind it: what they find replaces the band as soon as it is in.
**Recheck**, a **Configure** and a saved setting check again at once, and wait for it. It
is not drawn while everything is green. `ponos doctor` prints the same
checks (`src/ponos/health/`) — every one of them, `doctor` asks nothing on its own —
grouped as the band groups them (*Board*, *GitHub*, *Claude*, *Projects*, *Machine*,
*Settings*), with the settings it only describes in grey, which the band leaves out. The one
thing the two do differently: `doctor` asks the remote for the newest version, the dashboard
reads what the last check found.

### The rest of the file

The file holds about thirty keys — what somebody actually changes. Every other
setting is a constant of the code, at the value it always had by default, and is not in
the file nor in **Settings** (`ponos service run`, the same file drawn as a page). Every
key below is a field there; the file itself is `config.example.toml`, under 150 lines.

| Key | Default | Effect |
| --- | --- | --- |
| `runner.workspace_root` | `~/workspace` | where to look for repositories — and where one you have not cloned yet is cloned |
| `runner.interval_seconds` | `1800` | the daemon's safety net: it looks at the whole board — ready column, validated column, CI, reviews, merged pull requests, the mirror — at least this often, whatever woke it in between. A ticket made ready is started within seconds whatever this says; read again when the file changes |
| `runner.max_concurrent` | `2` | tickets handled side by side — an empty place is filled from the board without waiting for anything to end |
| `runner.timeout_minutes` | `30` | past this, the session is killed and the ticket fails |
| `runner.wait_for_credits` | `true` | a spent subscription window puts the runner to sleep instead of failing tickets — see [When the credits run out](credits.md#when-the-credits-run-out) |
| `runner.model` | `""` | `"opus"`, `"sonnet"`… empty = the CLI's default |
| `runner.language` | `""` | `"fr"` to be answered in French — see [The language it answers in](board.md#the-language-it-answers-in) |
| `runner.app_language` | `""` | the language the console opens in; empty follows `runner.language` — see [The language it answers in](board.md#the-language-it-answers-in) |
| `runner.base_branch` | `""` | empty = each repository's default branch |
| `runner.merge_method` | `"squash"` | how a **validated** pull request is merged — `squash`, `merge`, `rebase` |
| `runner.force_validated` | `[]` | the types of ticket validated as soon as their session succeeds, among `"code"` (the pull request is merged, then *Done*), `"publication"` (published without waiting in review), `"writing"` and `"external"` (which already end in *Done*, so they change nothing today) — see [*Force validated*](tickets.md#force-validated-skipping-the-review). Replaces the four `force_validated_<type>` booleans (`ponos config` converts them) |
| `runner.local_ci` | `false` | run the project's CI on this machine, in Docker, once the session has committed and before the push — the command the project's Settings tab declares, else its workflows through `act`; a red one goes back to the same session to be fixed. Needs Docker; a project may say otherwise for itself. GitHub's CI still runs |
| `runner.self_review` | `true` | before the push, a session in plan mode reads the diff against the ticket's done criterion and the project's CLAUDE.md; what it finds blocking goes back to the ticket's session once, then the pull request opens and its *Review* section says what was fixed and what was left. A project may say otherwise for itself — see [Read once before the pull request](tickets.md#read-once-before-the-pull-request) |
| `runner.unblock` | `false` | look once at a ticket that waits on its own, and answer it when the answer is already written |
| `runner.auto_update` | `true` | the daemon keeps the installation on the latest version, and restarts on it — its sessions taken back |
| `runner.update_channel` | `"release"` | what "latest" means: the newest `vX.Y.Z` tag, or `"main"` for every commit. No tag, no update; anything unknown reads as `"release"` |
| `runner.ideas_*` | off | the ideas schedule, written by the *Planned* page's dialog rather than by hand: `ideas_schedule`, `ideas_at`, `ideas_day`, `ideas_every_hours`, `ideas_cron`, `ideas_scope`, `ideas_projects`, `ideas_workspace`, `ideas_per_batch`, `ideas_skip_above`, `ideas_budget_usd`, `ideas_notify`, `ideas_model` |
| `budget.daily_usd`, `budget.per_ticket_usd` | no limit | the day's and one session's ceilings — see [Stopping before the wall](credits.md#stopping-before-the-wall) |
| `notify.desktop` | `true` | one desktop notification per finished ticket — `[notify]` carries it to your phone |
| `notify.events` | all three | which moments are sent: `blocked`, `failed`, `done` |
| `notify.digest` | `"off"` | `"daily"` or `"weekly"`: the summary of the period, sent on its own (Monday at 9 for the weekly one) |
| `notify.telegram.chat`, `notify.slack.channel` | `""` | where the messages go; `allowed_users` of each names who may answer and command — see *Telegram and Slack* |
| `web.host`, `web.port`, `web.url`, `web.email` | `127.0.0.1`, `8787`, `""`, `""` | the console's address and how it is opened — a token, or an email and a password. See *The web console* |
| `web.assistant_launches` | `true` | the console's assistant, and any MCP client allowed to write, may launch tickets with [`launch_task`](console.md#what-claude-can-do-with-it) — after showing them with their estimated cost and waiting for your yes; `false` refuses it, and tickets are launched from the console only |
| `web.library_max_mb` | `50` | the most a file of the [Library](console.md#library) may weigh, in MB; a heavier one is refused before a byte of it is kept |
| `claude.provider` | `""` | who answers the sessions — see *Who answers the sessions* below |
| `claude.attribution` | `false` | sign commits and pull requests as Claude — Claude Code's `Co-Authored-By` line and « Generated with Claude Code ». Off, every session is launched without them and what slips through is taken out of the pull request — see [Commits and pull requests are not signed as Claude](tickets.md#commits-and-pull-requests-are-not-signed-as-claude) |
| `permissions.allowed`, `permissions.ask` | | what a session does alone, and what always waits for your word |
| `github_access.mode`, `github_access.token_item` | `""` | how GitHub is reached without `gh` — see *Connect GitHub* below |
| `[github]` | | `"owner" = "gh account"`, when this machine answers to more than one GitHub — see *Several GitHub accounts* below |
| `[vault]` | | what each project's sessions are given — see *Keys a ticket may use* below |
| `install.extras` | `[]` | the optional extras every version's environment is built with — `"voice"` (Piper) and `"browser"` (Playwright); `ponos extras add voice` installs one and writes the line, and every update keeps it — see [Optional extras](installation.md#optional-extras-voice-browser) |
| `OPENROUTER_API_KEY` | | not a key of this file: the secret is in Ponos's vault or the environment (see the secrets above) — one key in front of every other provider, see *Every other model* below |

### What is a constant now

Everything else that used to be a line of the file is read as the value it had by default,
whatever a file still says: a line left behind is harmless, and `ponos doctor` names it so it can be
deleted. They are listed, with their values, in the *Breaking* entry of the
[changelog](../CHANGELOG.md): among them the guards (`min_free_memory_mb` 2048,
`max_load_per_core` 1.5, `min_free_disk_mb` 5120, `credit_reserve_percent` 5), the places per
project (`max_concurrent_per_project` 2), the branch (`branch_prefix` `ticket/`; fetch, push, pull
request and rebase all on), the conflicts (resolved by a session), the retention (`log_retention_days`
14, `stale_worktree_days` 30, `tmp_retention_hours` 24), the models (`auto_model` on, the four levels
`haiku`, `sonnet`, `opus` and `fable` — which stays off: `use_fable` `false`, so the heaviest level runs
on `opus` —, `review_model` `sonnet`, `classify_model` `haiku`), the console's polling and its
attachments (`web.poll_seconds` 15, `web.attachment_max_mb` 25), the voice (`[speech]`) and the
gateway of OpenRouter (`openrouter.base_url`, `openrouter.transcription_model`). `PONOS_WEB_TRUSTED_PROXIES`
still names the proxies a container trusts. The sessions run on OpenRouter exactly when
`claude.provider = "openrouter"`.

The board's columns, its statuses and the options of its `Type` column have **fixed names**
— they are not settings, and `ponos.db` holds every one of them.
The list is in [The tickets database](board.md#the-tickets-database).

One project (with a repository) holds at most two of those places (`max_concurrent_per_project`, a
constant): pull requests written side by side on one repository touch the same files, and each
one that lands makes the others conflict. A ready ticket whose project is already at the limit stays
in the column — the daemon says `project at its limit` — and the next ticket of another
project goes first; it starts as soon as a ticket of its project ends. Projects without a
repository (documents) are not counted.

`max_concurrent` is a number of **places**, not a batch size, and the daemon holds them
for as long as it runs. A place that frees — a session ended — or one never taken is filled
on the spot, from the board as it is *then*: the ready tickets by priority score, date, age,
a ticket that comes after another left where it is (« Après »), a project at its limit
passed over for the next one. So a ticket made ready at 14:10 starts at 14:10, not when the
two-hour session that began at 14:04 ends. The daemon looks when a place frees, when the
console, the MCP or `ponos run` moves a ticket to *Ready* (it is told at once), whenever the
ready tickets of `ponos.db` change (counted every two seconds, a local read), and every
`interval_seconds` whatever happens.

The *validated* column, the CI and the reviews of the pull requests in review, the merged
ones to close, the answers typed on a phone and the « On » prompts are seen to beside the
places, in a thread of their own, every `interval_seconds` — and at once when a ticket is
moved to *Validated*: a merge needs no place, it is two `gh` calls, and a publication takes
the next place that frees, before any ready ticket. Work you have accepted is one gesture
from done, and nothing about a session in flight has anything to do with it. See
[Validated, and what it sets off](tickets.md#validated-and-what-it-sets-off).

**Run now.** A ready card has a *Run now* button, and `ponos run --ticket <url>` does the
same: the ticket takes a free place at once, ahead of its turn. When none is free — every
place taken, or its project at its limit — the answer says so, and the console offers to run
it past the limit, once (`--force` on the command line): a place the limit does not count.

**Where it stands.** `ponos status` and the console's runner strip (click *places*) list the
places — which ticket holds each, per project — and the queue, each ticket with why it waits:
every place taken, its project at its limit, a ticket it comes after, a date, the credit or
the reserve. A ready card says it too when the wait is out of the ordinary — its date, the
credit, the reserve or the day's limit, a session still on it, or no daemon running. The
ordinary wait — every place taken — is not repeated on every card: the « In progress
N/max » header says it once. The daemon writes every reason in its log as they change,
starting with `…`.

A ticket moved back to ready is asked for again, whether or not it ran already: it is held
out only while a session is still on it — and fifteen seconds after, for the board to stop
serving its old status — then played again on its branch and its pull request.

`ponos run`, with a daemon running, only asks it to look now. With none — a checkout, a
test, a machine where the daemon is off — it is the scheduler for one run: it takes back the
sessions a dead daemon left, starts what is ready, keeps the places filled, and ends with its
last session. `ponos run --limit 3` then means three tickets for that run, not three at a
time.

### Preparing a worktree before the session

A worktree cut for a ticket has no `node_modules`, no `.venv`, no local `.env`. Left to itself, each session guesses what to install and pays for it in time and tokens — three to fifteen of them at once are as many installs. Give the project a **setup command** and it runs once in the fresh worktree, before Claude is started:

- in the project's **Settings** tab in the console (*Worktree setup*), e.g. `npm ci` or `uv sync`; or
- in the repository itself, as `.ponos/setup.sh`, run with `sh` from the root of the worktree. The project's own command wins when both exist.

Neither, and nothing runs: a ticket goes on as it always did. The command runs with the project's [vault](#keys-a-ticket-may-use-the-vault) keys in its environment, `CI=true` and `PONOS_SETUP=1`; its output goes to `<session log>.setup.log` beside the session's log. It is meant to be repeatable — a branch picked up again is prepared again.

The session is told the preparation has already run and not to install again. If the command fails, or outlasts `runner.setup_timeout_minutes`, the ticket is **blocked** with the code `worktree.setup-failed` and the last lines of the output, and no session is started or paid for; fix the command, answer on the ticket, and it runs again. `ponos doctor` lists the projects that have a setup command.

### Before and after captures of an interface ticket

Judging an interface ticket means starting the project and looking at it, which a phone cannot do. Give the project a **preview** — in its **Settings** tab (*Before and after captures*): the command that starts it (`npm run dev`), the address it answers on (`http://127.0.0.1:5173`) and the pages to photograph (`/`, `/settings`) — and every code ticket of that project comes back with pictures.

After the commits, the runner starts the command on the branch and photographs each page with the installed Chrome (headless), then does the same on a detached checkout of the base — prepared with the project's [setup command](#preparing-a-worktree-before-the-session) — and kills the processes it started, the whole group, whatever happened. The pairs are kept in the state directory (`previews/<ticket>/`), shown side by side on the ticket's page and in its **Decide** tab, and posted as a comment on the pull request. GitHub takes no picture through its API, so the runner pushes them in a commit of their own, outside any branch (`refs/ponos/previews/<ticket>`: no branch to list, no CI started), and the comment shows them from it; if that push is refused, the comment links them from the console instead, which needs `[web].url` and only opens for you.

Nothing starts when the preview is empty. An address that already answers before the launch is never photographed — it would not be the branch's page — and a missing Chrome, a server that stops or never answers (90 s), or a failed capture is a line in the ticket's report: the ticket goes to review without pictures, as before. The server's output is in `<session log>.preview.log`.

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
| `"api_key"` | An Anthropic key: `ANTHROPIC_API_KEY`, in Ponos's vault or the environment | Billed by the token. No browser, nothing to wait for. |
| `"openrouter"` | The OpenRouter key (below), `OPENROUTER_API_KEY` | The sessions run there, and a model is an OpenRouter slug. No browser, nothing to wait for. |

An empty `provider` is a file written before the key existed: the sessions run on the CLI,
whatever key is there. A key
in the file wins over the one in the environment, which only fills an empty line — a key
somebody has just typed and checked must not lose to one a compose file was started with.
An Anthropic key is handed to a session only when it is the provider: given to a CLI
session, it would quietly take the place of the subscription.

In the console the key is **Settings › Models and costs › Provider and default model ›
Anthropic API key**, with the provider just above it — choose *Anthropic API key* there, or the
sessions keep running on the CLI. The key is sealed in Ponos's vault, never written to
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
# Settings › Models and costs (sealed in Ponos's vault) — or the environment
OPENROUTER_API_KEY=sk-or-v1-...
```

That alone changes nothing about the runner. The key is simply *there*, in the environment
of every session it starts, as `OPENROUTER_API_KEY` — the name every library and every
snippet already looks for. So a ticket can have a GPT write the copy, a model transcribe an
audio file or another make the video, and pay for it, without the runner having to know
what any of those are.

The other way is a decision rather than a convenience:

```toml
[claude]
provider = "openrouter"
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

The provider is a field of the console's **Settings** tab, and so is the key; the
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
tokens are never shown, in the console, the logs or a ticket: the credentials are one
secret of Ponos's vault (`PONOS_GITHUB_APPS`), sealed like the others.

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
  in Ponos's vault (what the console writes), or in the environment — which is how a
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
a ticket is the worst place to write one: it is a page of the board, a prompt, a transcript and
sometimes a pull request. So keys stay where they already live, and `[vault]` says two
things: **where** they are read, and **which ones each project is given**. The first stays in
`config.toml`; the second is set per project, in the project's Settings tab (*Vault keys*, one
`NPM_TOKEN = hermez/npm` per line — a bare name is read under its own name), and kept in `ponos.db`.
A `[vault.projects]` table of an older file is moved there by [`ponos config`](#a-file-from-an-older-version-ponos-config).

```toml
[vault]
provider = "pass"                 # env, keyring, pass or bitwarden
```

and, in the *Vault keys* of the project's Settings tab:

```text
NPM_TOKEN = hermez-agency/npm     # the variable the session sees = the item it is read from
GH_DEPLOY_TOKEN = keyring:ponos-deploy   # one key that lives somewhere else
LEADZ_DOKPLOY_TOKEN               # alone: read under its own name
```

| `provider` | Reads | What it needs |
| --- | --- | --- |
| `env` (default) | the runner's environment, then Ponos's own secrets in its vault (where a `secrets.env` from before was moved) | nothing |
| `keyring` | the GNOME keyring, or any Secret Service, through `secret-tool lookup` — a bare name is `service ponos username <name>`; `attr=value attr=value` finds any other item | `libsecret-tools`, and a keyring unlocked by your session |
| `pass` | the first line of `pass show <item>` | `pass`, and a `gpg-agent` that has the passphrase |
| `bitwarden` | `bw get password <item>`, by name or id | the Bitwarden CLI, unlocked: `BW_SESSION` in the environment (`bw unlock --raw`) |

Those keys reach the sessions of **that project's tickets, and nobody else's**, as
environment variables. The prompt tells the session their names — never their values —
and asks it to use them as `$NPM_TOKEN` and never print them. A project that names no key is
given nothing; the runner's own variables (`PONOS_*`, `ANTHROPIC_API_KEY`, the
OpenRouter key) are never handed to a project, and win over a key of the same name. Each
key is read again at every session, so a token rotated in the keyring is the one the next
ticket gets; one that cannot be read is said in the log, by name, and the ticket runs
without it.

And a value read is a value **masked**. A session may still print its key — an `env` to
debug a deploy, a verbose `npm publish` — so every value read is replaced by `***` before
anything goes out: the comments and pages written to `ponos.db`, the
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
   # or, with no vault at all, an entry of Ponos's own (Context → Vault, below):
   #   ponos vault set NPM_TOKEN --project Ponos
   ```

3. Grant it to the project: `provider = "pass"` under `[vault]` in
   `~/.config/ponos/config.toml`, and in the *Vault keys* of the Ponos project's Settings tab:

   ```text
   NPM_TOKEN = hermez-agency/npm      # or keyring:hermez-agency-npm, or env:NPM_TOKEN
   ```

4. `ponos doctor` reads it, and answers `✓ Vault: Ponos is given NPM_TOKEN.` — or why it could not. A
   ticket of Ponos can then publish with `NPM_TOKEN` in its environment (an `.npmrc` that
   says `//registry.npmjs.org/:_authToken=${NPM_TOKEN}`). Publishing on a public registry
   is still one of the actions it asks before, whatever key it holds.

Another provider — 1Password's `op read`, say — is one class in `src/ponos/vault.py` with a
`read(item)` and an `available()`, and one line in its `PROVIDERS`.

### Ponos's own vault: Context → Vault

On a machine with neither `secret-tool`, `pass` nor `bw`, every key used to end up in the
environment or in a `secrets.env`, in clear. The `ponos` provider is the vault that needs
nothing installed: **Context → Vault** in the console (an admin's — a member or a reader
does not see the page, and the API answers them 403), or `ponos vault` in a terminal.

An entry is one of three kinds — an **API key / token**, a **login + password** (given as
`<NAME>_USER` and `<NAME>_PASSWORD`), a **secret note** of several lines (a certificate) —
with the name of its variable, the **projects allowed** (none by default), a description,
an optional expiry date and an optional **site**. It reaches the sessions of those projects' tickets as an
environment variable, the way every `[vault]` key does, and is masked the same way;
nothing more is needed in `config.toml`. A line of `[vault]` may still name one —
`NPM_TOKEN = "ponos:NPM_TOKEN"` — and wins over the page for the same variable. The
console's chat, which is no ticket, is given none of them.

**The site of an entry.** Any entry may say where it is used: the sign-in page of a login,
the dashboard where a token is managed or renewed (OpenRouter's keys, Dokploy, a cloud
console). It is typed when the entry is made, and changed later with *Site* on its
row; only an `http://` or `https://` address is kept — a bare host is read as `https://`
it, anything else (`javascript:`, `ftp:`, a space in it) is refused with a message under
the field. The list shows it as a link, by its domain alone, that opens the whole address
in a new tab. It is no secret: it is kept in clear in `vault.db`, beside the name — but
it is sealed with the value all the same (below), so an address changed in the file by
hand opens nothing. The sessions given the entry are given it too, as `<NAME>_URL` beside
the other variables (`NPM_TOKEN_URL`, `DOKPLOY_URL`), unmasked, and the prompt names it
apart from the secrets: an address, not a value to hide. That name is the entry's even
when it has no site yet: an entry called `DOKPLOY` and another called `DOKPLOY_URL` cannot
both be kept, nor an entry whose `_URL` would be one of the runner's own variables. Each
change of the site is written in the entry's journal, with what it became.

**Write-only.** Once kept, a value is never answered again — not by the API, not in a
refusal, not in a log. The list shows the name, the projects, when it was created and
changed, when a session was last given it and the end of the value (four characters,
nothing under twelve). There is no *show*: a value is replaced, or revoked — for good,
after a confirmation. Every write asks for the console's password again, unless it was
typed less than five minutes ago (signing in counts); a console opened with its token
alone takes the token.

```sh
ponos vault set LEADZ_DOKPLOY_TOKEN --project Leadz   # asks for the value, without echo
printf '%s\n%s\n' admin "$PASSWORD" | ponos vault set DOKPLOY --kind login --project Leadz \
  --url https://dokploy.example.com/login              # its site: DOKPLOY_URL in a session
ponos vault list                                       # names, projects, sites, last use — never a value
ponos vault rm LEADZ_DOKPLOY_TOKEN
ponos vault rotate                                     # every entry sealed again under a new key
```

**How it is kept.** `vault.db`, in the state directory (`~/.local/state/ponos`), `0600`.
Each entry is sealed on its own with AES-256-GCM, with a random 96-bit nonce at every
write; the entry's id, name, kind, projects and site are its associated data, so a sealed
value copied onto another entry, a byte changed, or a project or a site changed by hand in
the file, no longer opens. A vault sealed before the site was part of it is sealed again
with it, once, the first time it is opened. The 32-byte master key (`secrets.token_bytes`, no passphrase) is never kept
beside the data — in this order:

1. the system keyring, when `secret-tool` is installed;
2. else `PONOS_VAULT_KEY` (base64 or hex), given by the unit file or by Dokploy — the
   sessions never inherit it;
3. else `~/.config/ponos/vault.key`, `0600`. The page says where the key is, and
   `ponos doctor` warns: a backup that holds both files holds every key.

`ponos vault rotate` seals every entry again under a new key, kept where the old one was;
the old one opens nothing any more. With `PONOS_VAULT_KEY`, the new key is printed once,
to set in its place before Ponos starts again. `ponos doctor` also checks the modes of
`vault.db` and `vault.key`, the entries past or within 14 days of their expiry, and those
granted to no project.

**What it protects, and what it does not.** It protects a copy of `vault.db` on its own —
a backup, a volume moved to another host — and every place the runner writes: a value a
session is given is masked in its transcript, the ticket's comments in
`ponos.db`, the log, the console's answers and stream, Telegram, Slack and the push
notifications. Each entry's journal (Context → Vault, the history of an entry) says when
it was created, replaced, given other projects or another site, revoked, and given to which ticket's
session — never the value. It does **not** protect from somebody who has the Unix account
that runs Ponos: that account reads the key wherever it is kept, and can ask the runner
itself.

### Ponos's browser: external tickets that sign in on their own

An *external action* — open Dokploy and read the list of projects, change a setting in
Brevo — used to run in **Claude in Chrome**, your own Chrome: it had to be open, with its
extension connected and the right account active, two sessions in it stepped on each
other, and a sign-in form stopped the ticket until somebody typed the password. Ponos now
has a browser of its own: **Chromium driven by Playwright**, on the machine Ponos runs on,
without a window unless you ask for one. Install it once —
`ponos doctor` prints the two commands for yours:

```sh
ponos extras add browser   # the `browser` extra: Playwright, kept by every update
python -m playwright install chromium
```

Ponos's browser is the default, and runs without a window: both are constants (`[browser]
default` and `headless`, no longer keys of `config.toml` — a file that still holds them is
read without them). Claude in Chrome stays one line of a ticket or one setting of a project away.

**Which browser.** Only external tickets are concerned: a publication still posts from your
own accounts, in your Chrome. A ticket names its browser with a line of its body —
`Browser: chrome`, `Navigateur : Ponos` —, else its project's settings say (the
**Browser** card of a project's Settings tab), else Ponos's browser. On a machine
without Playwright or its Chromium, the ticket runs in Claude in Chrome and the runner
says why.

**What the session gets.** An MCP server, `ponos-browser`, in place of Claude in Chrome,
with `browser_navigate`, `browser_read` (the page's accessibility tree or its text),
`browser_click`, `browser_type`, `browser_press`, `browser_screenshot`, `browser_download`
and `browser_upload` (files of its working directory), and `browser_login`. Every session
starts a browser and a context of its own: two tickets browse at the same time without
meeting.

**Signing in without the password.** A *login + password* entry of the vault takes a
**site** — the address of its sign-in page (Context → Vault, *Site*; `ponos vault set
NAME --kind login --url https://…`). The prompt names the logins granted to the ticket's
project, and nothing else; the session calls `browser_login` with one of those names, and
the browser opens the site, finds the user and password fields, fills them, submits, and
answers one of three things: *connected*, *failed* with the reason, or *second factor
requested*. The model never holds the value: it is read inside the server, every word
sent back — a page's text, its tree, an error — has the vault's values and the password
fields masked, screenshots are taken with those fields hidden, and `browser_type` refuses
to type a value of the vault the model would have copied or guessed.

**Where a login is typed.** Only for the projects the entry is granted to, and only on the
host of its site or one of its subdomains: a sign-in asked on another host, or a page that
sends the browser to another one, is refused before anything is typed — the guard against
a page that only looks like the right one. Every sign-in is written in the entry's journal:
the ticket, the project, the date, and whether it was connected, failed, stopped on a second
factor or refused.

**A second factor, a CAPTCHA.** The browser never answers them. `browser_login` says so,
with a screenshot in the ticket's folder, and the session ends *Blocked* asking you to
finish. On the project's Settings tab, **Browser → Sign in here** opens the site in a
browser on the project's profile, shown live on the page: click on the picture where you
would click, type the code, *Done, close it*, and answer the ticket « done » — it resumes
signed in. A session that is running shows in the same card, live.

**One profile per project.** The cookies and the local storage a session leaves are kept
per project in `~/.local/state/ponos/browser/profiles/<project>.json`, `0600` in a `0700`
folder like `vault.db`, and merged back at the end of each session, so a site signed in
once stays signed in for the next ticket. The card lists the sites the profile holds
cookies for, and **Reset** signs them all out. Out of scope, on purpose: getting past a
CAPTCHA or a second factor, signing in with Google or another OAuth provider in your
place, and filling in a means of payment. Irreversible actions — sending, paying, deleting,
publishing — stay under the rules of external tickets: the session stops at its first
doubt.
