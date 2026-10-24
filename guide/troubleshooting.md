# Troubleshooting

[The guide](README.md) · [Ponos](../README.md)

## While installing

| Where it stops | What to do |
| --- | --- |
| the installer prints `✗ … is missing` | run the command printed under it, then the install line again — everything missing is listed at once |
| `Failed to connect to bus` (an older installer) | there is no systemd user session here — WSL, a container, SSH: install again, the console is now started without it |
| the browser does not open | open `http://127.0.0.1:8787` yourself; nothing answers? `ponos serve` starts it and says why it cannot |
| `ponos: command not found` | `~/.local/bin` is not in your `PATH` — the installer prints the line to add |
| Notion shows no page in the console | the page is not shared with the integration: `···` at the top right of the page → *Connections* → your integration. The console sees it within seconds |
| the demonstration ticket fails | the console shows what the run said. *Run the full diagnosis* on the summary is `ponos doctor`, and is the text to paste when asking for help |

[When it does not work](#when-it-does-not-work) has the rest, once Ponos runs.

---

## When it does not work

| Symptom | Most likely cause |
| --- | --- |
| `object not found` on the database | the page is not shared with the integration (`···` → Connections). Sharing the page that holds the workspace covers everything under it |
| a comment gets no answer | the integration cannot read or write comments (`Capabilities` → *Read comments*, *Insert comments*), or the comment is not addressed to it — reply under one of its reports, or name it. `ponos doctor` says which |
| “no page named … in the workspace” | the row is called something else. `doctor` lists what it did find — rename the row, set `[notion.pages]`, or run `ponos init` to create it |
| the agent knows nothing about you | no `Context` row in the workspace, or the page is empty. `doctor` says which, and the run says so once |
| “comments not readable” | the integration lacks *Read comments* (my-integrations → Capabilities). The ticket runs, without its discussion, and answering it in a comment no longer wakes it |
| a comment on a ticket changes nothing | the ticket is *done*, or no run of this host ever reported on it — those two never wake |
| a ticket keeps running again and again | its report never gets posted, so your answer stays the last word: the integration lost *Insert comments* |
| a ticket ignores its agent | the `Agent` column is missing or is not a relation — `doctor` names it |
| “project not found on disk” | none of what the project declares leads to a repository — the comment lists each way that was tried and why it failed. Fix its `Path` or `Repository` property, or add `"Notion name" = "/path"` under `[projects]` |
| a ticket ran, but its comment says a declaration is wrong | the repository was found by a fallback: a `Path` pointing nowhere, or a `Repository` GitHub has since renamed. Correct the project page — `ponos projects` shows it with a `!` until you do |
| a ticket became a document when you wanted code | its project names no repository. Give the project page a `Path` or a `Repository` |
| “nothing to work from” | the ticket has neither a title nor a description — a page left on the bare template counts as empty |
| a report says Notion “may have applied” a write | the answer to a comment, a new page or appended blocks timed out *after* it was sent — or Notion answered 5xx. It is not sent again, because a duplicate is worse than a gap: look at the ticket, the write is usually there. Reads and property updates are retried up to four times, and a `429` waits what its `Retry-After` asks, up to a minute |
| a ticket failed with “the runner itself broke” | something raised while that ticket was being handled — a board that stopped answering, a bug. The comment carries what was raised, and the other tickets of the pass ran on. A git or `gh` command that outlives its timeout is not one of those any more: it answers as a failed command (code 124), which every step already knows how to report |
| a ticket sat in *In progress* forever | it no longer can: the next run puts back any ticket this host claimed while no run was alive |
| the timer is on and nothing moves | the subscription's window is spent — `ponos status` says until when. Tickets are where they were, and the first run after that takes them again |
| a ticket ran before and its branch is still there | it is picked up, not refused: the branch is checked out again and rebased onto the base branch, and the session continues from what it already holds. The ticket's comment says so, and says when the rebase conflicted. `ponos clean --force` is what starts it over instead |
| `branch … is checked out in …` | two attempts at the same ticket at once, or a worktree kept somewhere else — the one case that still stops it. `git worktree remove <path>`, once you are done with what is in there |
| no desktop notification | `notify-send` is missing, or the service has no session bus. `runner.notify = false` silences the attempt |
| a desktop notification that does not open its ticket | the click needs `gdbus`, `dbus-monitor` and `xdg-open`, and a desktop that says it supports notification actions. Without them the notification is shown as it always was |
| nothing arrives in Telegram or Slack | `ponos notify` says which end refused — a revoked token, a chat id that is not yours, a bot not invited to the channel |
| an answer typed in Slack changes nothing | the bot cannot read the channel: add `channels:history` (or `groups:history`, `im:history`) and reinstall the app |
| an answer lands on the wrong ticket | a bare “oui” answers the last question asked. Reply *to* the message, or paste the ticket's link, when two are waiting |
| the runner talks but never listens | `notify.replies = false`, or the run is a `--dry-run`: answers are only read at the top of a real run |
| the timer does not fire with no session open | `sudo loginctl enable-linger $USER` |
| `status` says the timer has no next run | it was restarted, with a unit written before this fix, after a run that failed — and will never fire again: `ponos enable` rewrites the unit and restarts it |
| the version never moves | the install directory is a copy, not a clone: an installation older than self-updating, or one made with `TR_SRC`. `doctor` says which — run `install.sh` again |
| branch pushed, no pull request | `gh` cannot reach its credentials from a systemd service — locked keyring. Use `gh auth login` with a token, or set `GH_TOKEN` in the unit |
| `claude: command not found` in the journal | the PATH baked into the unit predates a node version change: run `install.sh` again |

Session logs are in `~/.local/state/ponos/logs/` (one `.jsonl` per ticket, the raw
session stream), the history in `ponos.db` (`ponos history`), and the timer's own journal in
`journalctl --user -u ponos -f`.

The runner and the console also keep a journal of their own, `ponos.log`, in the same
`logs/` directory: every line they print, dated and levelled, and — which the standard
output never shows — the full trace of every error they caught, a route of the console
that answered a 500 included, and a line for each request that came back 4xx or 5xx. It
turns over at a megabyte and keeps five files behind; `ponos clean --days` drops the old
ones with the session logs. Values read from a vault and anything shaped like a token
(`ghp_…`, `sk-…`, `ntn_…`, a Telegram bot token…) are masked before they are written.
`ponos logs --service` prints its end (`-f` follows it), and the console shows the same
lines in **Settings**, under *What this console runs on*, with **Read the journal**.

`~/.local/state/ponos/ponos.db` is the runner's local memory — a SQLite file, kept
beside the board rather than instead of it. Its schema is numbered and brought up to date
the first time a process opens it; `ponos doctor` opens it and says at which version it
is, and a file written by a newer Ponos is refused untouched rather than read: update
Ponos instead.

Each migration is remembered by its name, in the `migrations` table, and not only counted:
one the file has not been through is applied wherever it sits in the list, and one it went
through under another rank — a branch's code, not yet rebased, migrated it in its own order
— is not applied twice. A file that names a migration this code does not know is refused
the same way as a newer one, and `ponos doctor` warns when the names are not in the code's
order. A file from before the table is given the names of its first migrations, by its
version.

Launched from a repository rather than from its installation — `PYTHONPATH=src python3 -m
ponos …` in a checkout or a worktree — Ponos refuses to touch the real state until
`XDG_STATE_HOME` is set: `XDG_STATE_HOME=$(mktemp -d)` for a state of its own, or
`XDG_STATE_HOME=~/.local/state` to really work on the installation's. The tests set it.

It holds what used to be a dozen JSON files beside it — the history, the claims, the replay
counts, the conversations, the credit waits, the Markdown mirror's stamps and journal, the
index of project pictures. An installation that still has them reads each one in, once,
the first time the new version starts, and renames it `<name>.imported`: nothing is
deleted, and once you have checked that `ponos history` and the console say what they
said, the `.imported` files can go. The session logs stay files, under `logs/`.

#### The run journal

Every run — one session on one ticket — is a row of `ponos.db`, and every step of it a
row under that: what the agent said, which tool it called on what (a command, a file),
which call failed, when, and what the run had cost so far when that is known. It is
written as the session goes, whatever the board — Notion, Markdown or both — and whatever
`runner.progress` says; it is closed with what the ticket came to (*done* with its pull
request, *blocked* with its question, *failed*, *waiting* for credit). A run the runner was
killed in keeps no status, and reads as such.

It is what the console's **live** tab reads, a page at a time, and what `ponos logs
--runs` lists. The ticket's page keeps only the agent's sentences and the result; the
`.jsonl` beside it stays the complete record — what a command printed, what a file held —
which the journal does not copy. A database that cannot be written switches the journal
off for that run, and the ticket goes on.
