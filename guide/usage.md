# Every command

[The guide](README.md) · [Ponos](../README.md)

The `ponos` command, from a terminal.

## Usage

```sh
ponos init <url>   # build (or complete) the Notion board under a page
ponos init <url> --token <token>  # the same, saving the Notion token (--no-demo: no demonstration ticket)
ponos config       # open config.toml in your editor
ponos list         # the ready tickets, and their project
ponos run          # one run, right now
ponos run --dry-run          # what it would do, touching nothing
ponos run --ticket <url>     # that one ticket, whatever its status
ponos run --limit <n>        # at most that many tickets in this run
ponos run --every [seconds]  # keep running: one run every interval, where there is no systemd
ponos logs -f      # follow the running session (--follow)
ponos logs <ticket>          # the last session of that ticket (--raw: the raw JSON stream)
ponos logs <ticket> --runs   # the ticket's runs, from the local journal
ponos logs --service         # the runner's and the console's own log, ponos.log
ponos status       # timer, console, current run, recent tickets
ponos history      # what has been handled, with the pull requests (-n, --number: how many)
ponos projects     # Notion project → local repository mapping
ponos subtypes     # the code tickets by sub-type
ponos subtypes --backfill    # fill the empty ones from their prefix (--dry-run: write nothing, --all: done and cancelled ones too)
ponos schedules    # what comes back on its own, and when it next does
ponos schedules --run <name>  # make its ticket now, without waiting for the hour (--force: even if the last one is still open)
ponos sync         # reconcile the Notion board and the Markdown one
ponos sync --journal         # what past reconciliations carried, and what they refused (-n, --number: how many)
ponos doctor       # full diagnostics
ponos clean                  # empty worktree directories that are only root-owned residue (no .git)
ponos clean --force          # remove worktrees, their branches, and scratch dirs
ponos clean --force --days <n>  # and drop the session logs older than that many days (default 14)
ponos update       # move the installation to the newest version
ponos update --check         # what is available, changing nothing
ponos update --environment   # make the .venv of the version in use again
ponos enable       # apply interval_seconds, start the timer and the console
ponos disable      # stop the timer and the console
ponos serve        # the web console, in this terminal (it already runs on its own)
ponos serve --host <address> --port <port>  # bind elsewhere than web.host and web.port
ponos serve --print-token    # print the console's token, and exit
ponos serve --sign-out-everywhere  # end every browser's and every connector's sign-in, and exit
ponos open <uri>   # what a ponos://session/<id>?cwd=<path> link runs on the desktop
ponos tailscale [status|apply|enable|disable|watch]  # the console on your tailnet, MCP through Funnel (--interval: seconds, for watch)
ponos notify [message]       # send yourself a test message on Telegram or Slack
ponos notify --pair          # find your Telegram chat id and save it
ponos mcp token    # a key to the MCP server, for a client that cannot sign in (--read-only, --name)
ponos mcp list     # the address to paste in Claude, the MCP clients and their last writes (-n, --number: how many)
ponos mcp revoke <client>    # take back every key of one client
```

The first attempt is best made by hand, on a ticket you choose:

```sh
ponos run --ticket https://www.notion.so/... --dry-run   # look first
ponos run --ticket https://www.notion.so/...             # then go
```

### Exit codes

What a script, a cron line or a container's healthcheck can read from `$?`:

| Code | Means |
|------|-------|
| `0` | Done — and also a pass that finds another one holding the run lock, or a network that is down: the next pass is the one that does the work. |
| `1` | A problem to look at: `doctor` or `sync` found some, the board could not be read, a `run` whose every ticket failed (one failed out of three is still `0`). |
| `2` | Nothing was tried: the configuration cannot be read or is unusable (`run`, `status`, `doctor`, `init`, `notify`…), a command line `ponos` does not understand, or a checkout refused because it would write the real state. |
| `130` | Stopped with Ctrl-C. |

### What `clean` removes, and what it refuses to

A branch is named after its ticket, so it is the same name on every attempt. A
run that finds it there picks it up rather than refusing the ticket — the branch
is checked out again, replayed on top of the newest base, and the session
continues what the last one committed. `clean --force` is what you run when you
would rather it started over: it removes the branch along with the worktree, but
only when nothing on it is anybody's but the runner's.

A branch with commits of its own that are not on the base branch, one whose pull
request is still open, or a worktree holding changes that were never committed:
those are kept, named, and given the reason. That ticket stays blocked until you
look at it — which is the point, since a commit that failed to push is sometimes
the only copy there is — and the line printed under it is the command that drops
the branch once you have what you need.

`clean --force` takes the run lock, and refuses while a run holds it: a worktree kept by a
failure and the worktree a session is working in right now sit side by side, and nothing
on disk tells them apart. And it only ever acts on a repository that claims the directory:
a directory counts as a worktree when it carries git's `.git` *file* and the repository
that file names lists it among its worktrees. Anything else — a scratch directory, a clone
a session made inside one — is removed as a directory, and git is never asked from inside
it, where it would have climbed to whatever repository the state directory sits in.

Nobody has to remember it, though. Once a day a run tidies on its own — the
retention is `log_retention_days`: session logs older than that — and in `ponos.db`
the steps of the runs of that age (the runs themselves stay, with their outcome and
cost), the sync journal, the MCP calls and the finished transitions, the file being
compacted once a quarter of it is free — and, with
`clean_done_worktrees` on, the worktrees and scratch directories of tickets the
board says have been **done** or **cancelled** for that long, plus the scratch
directories of tickets no longer on the board. A ticket in progress, blocked,
failed or in review keeps its directory until `stale_worktree_days` (30) have
passed without anything touching it; even then a worktree whose ticket is in
progress, or that holds uncommitted changes or commits no remote has, is kept
and named. A branch is deleted only when a remote holds all its commits.

The disk is watched too. Under `min_free_disk_mb` free, the run tidies before it
starts a ticket (at most every ten minutes), and if the space is still short it
starts nothing — the ticket stays in Ready, not Blocked, and the console and a
notification say so. `worktree_exclude = "docs/media"` makes new worktrees
without those folders (a sparse checkout, decided before the first file is
written), so a repository's videos never fill the disk once per ticket. The
*General* page of the console's settings shows the space the three directories take, with
a **Clean up** button that applies the same retention straight away — once confirmed, since
what it removes does not come back — and
`ponos doctor` says both.
