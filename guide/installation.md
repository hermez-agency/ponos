# Installing Ponos

[The guide](README.md) · [Ponos](../README.md)

Installing, updating and uninstalling.

## Installation

[The install line](../README.md#install-it) runs `install.sh`. The script checks the machine
first and says everything that is missing at once, each with
the command that installs it here — `apt-get`, `dnf`, `pacman` or `brew`, whichever this
machine has — and ends on one line that installs them all (`sudo apt-get install -y python3 python3-venv git`); it picks the newest Python that is recent enough, `python3.12` beside an older
`python3` included, and offers to install Claude Code when it is not there. Then it installs
the `ponos` command into `~/.local/bin` and starts **the daemon**, `ponos daemon`: one
process that holds the places (`max_concurrent`, `max_concurrent_per_project`) and starts
the next ready ticket — by priority, a ticket waiting for another left where it is — the
moment one frees. A ticket moved to *Ready* from the console, the MCP or `ponos run` wakes it
at once; one made ready anywhere else is seen within seconds, and the board is looked at again
every `interval_seconds` (30 minutes by default) whatever happens, as a safety net:

- **Linux with a systemd user session** — `ponos.service`, always on (`Restart=always`), and
  the console as a service. An installation from before the daemon had a timer,
  `ponos.timer`: the daemon turns it off and removes it the first time it starts;
- **macOS** — two launchd agents in `~/Library/LaunchAgents`, `app.ponos.run` (the daemon,
  kept alive) and `app.ponos.web`, logging under `~/.local/state/ponos/`;
- **neither** — WSL, a container, an SSH session with no user bus: no systemd, so the
  installer starts two processes in the background — the console, and `ponos daemon`. Both
  last until the machine restarts: start them again with `ponos service run` and
  `ponos daemon`. `ponos doctor`, `ponos status` and the console's runner strip say the same
  thing — and `doctor` warns, rather than ticking, when no daemon is running.

**The sessions are not the daemon's children.** Each Claude session is held by a small
process of its own (it writes the session's log and how it ended), written down in
`ponos.db` with its ticket. Restart the daemon — `ponos service on`, an update, a crash — and
the sessions carry on; the daemon that comes back takes each one back, reads it to its end,
and does the rest of its ticket: the push, the pull request, the status. The unit is
`KillMode=process` for that reason: stopping it never stops a session.

It ends by opening the [web console](console.md#the-web-console) on `http://127.0.0.1:8787`, where the
[first connection](console.md#the-first-connection) does the rest; `TR_NO_WEB=1` leaves the console
stopped, `TR_NO_OPEN=1` only skips the browser. Nothing is asked in the terminal any more.
Later,

```sh
ponos doctor
```

tells you, line by line, what is still missing — the same text as *Run the full diagnosis*
in the console.
GitHub is not among them until a project of the board has a repository: before that, a
machine without `gh` or a GitHub App gets an information line — no pull request until GitHub
is connected — and `doctor` still exits 0.

Running the same command again **updates** the installation: the code is replaced, your
configuration is kept.

What it installs is **the newest release** — the highest `vX.Y.Z` tag of the repository,
the one the updates below follow — and not the tip of `main`: `ponos --version` prints that
number, and `ponos doctor` finds nothing newer. `TR_REF=main` installs the tip of `main`
instead, and sets `runner.update_channel = "main"`, so that the updates follow every commit
rather than wait for the next release; a repository with no release yet is installed from
`main` the same way.

You will rarely need to. The installer clones the repository into
`~/.local/share/ponos/app`, which is what lets the runner answer *"am I still on
the latest version"* with one `git fetch`. The daemon asks **once an hour**
(`update_interval_seconds`), and if the answer is no it installs the new version beside the
one in use — the launcher and the systemd units included — then restarts itself on it: an
`exec`, same process, new code. It waits, to do so, only for what a restart could not carry
on (a push, a merge, a reply under way, never more than a few minutes); the Claude sessions in
flight finish on the code they started with, and are taken back by the new daemon. Everything
that starts afterwards runs on the new version.

What it asks about is **the newest release** — the highest `vX.Y.Z` tag on the remote —
and not the tip of `main`. A commit merged into `main` is not something every installation
should be running an hour later; a release is somebody having said *this one*. No release
tagged yet means no update at all, and the run says so rather than falling back on `main`;
an installation already ahead of the newest tag is left where it is rather than taken back.
To tell which of the two is ahead, the first check fetches, once, the history that the
shallow clone of `install.sh` left out.
`runner.update_channel = "main"` is the other answer, for whoever wants every commit as it
lands.

```sh
ponos update --check   # what is available, changing nothing
ponos update           # apply it now
ponos update --environment  # make the version in use its .venv again, nothing else
```

**From the console**, the version at the top right is the release number followed by the
commit it runs — `0.1.0+1a2b3c4`, read from git when the header is drawn, so it changes with
every commit without anybody bumping it; outside a git checkout (a copy, the Docker image)
it is the number alone. Hovered, it gives the full hash, the date and the subject of that
commit. The console also asks the remote itself, when it starts and every 15 minutes (one
`git fetch`, whatever the number of pages open, and none with `runner.auto_update = false`)
— without counting as the hourly check a run makes, so the runs keep updating on their own.
The day a check has found a newer version, an amber *Update* button appears beside the
number, with how many commits behind it is; hovered, it lists their subjects and names the
installed version and the one waiting; clicked, it shows both, links the release notes (or
the commits in between, on `main`), and asks before doing anything. *Update now* then does
what `ponos update` does, with every step drawn as it happens — downloading,
installing, restarting — and the page reloads by itself from the new version:

- **nothing running is cut short.** The new version is put in place beside the one in use,
  then the daemon is asked to restart on it, which it does as above: the sessions in flight
  carry on and are taken back. Only another install under way (the daemon's own) is waited
  for, and a chat turn or a command typed in the console — the update can be called off
  meanwhile;
- **a failure leaves the old version.** The new code is started by a Python of its own
  before it is kept; if it does not start, or its launcher and units cannot be written,
  the installation goes back to the commit it replaced, the dialog says why, and the log is
  there — in the dialog, and in `~/.local/state/ponos/web/update.log`. The same
  holds for an update made by the daemon or by `ponos update`;
- **nothing runs on half of two versions.** Each version is installed in a directory of
  its own, `~/.local/share/ponos/app-<commit>`, and `app` is a link moved onto it
  in one step once it starts. A process reads the link once, when it starts, and runs whole
  on the version it found — the daemon reads it again when it restarts itself; the previous version stays on disk beside the new one, and
  `ponos.db` as it was before the new one migrated it, as `ponos.db.v<N>.bak`
  (see [Troubleshooting](troubleshooting.md#when-it-does-not-work));
- **each version has its own Python environment.** `app-<commit>/.venv` is made from the
  machine's `python3` before `app` points at the version, and holds what
  `requirements.txt` lists — httpx and pydantic for the runner, cryptography for the pushes to a phone, the console's FastAPI and uvicorn, and
  the few packages they pull in, at the versions of `uv.lock`, hashes checked;
  [uv](https://docs.astral.sh/uv/) installs them when the machine has it, pip otherwise (on
  Debian and Ubuntu, pip in an environment comes with `python3-venv`). A version whose
  environment cannot be made, or whose console does not import in it, is never pointed at,
  and the one in use keeps its own. An installation updated by a version from before
  environments gets its `.venv` the next time the daemon starts, with nothing to do: until
  then, and on a `python3` that cannot make one at all, the launcher runs the machine's
  `python3` as it always has — where the daemon, which cannot read `config.toml` without
  pydantic, makes the environment and starts again in it —, and the console says what it is
  missing and starts again on the environment once it is made;
- **no `pip` is needed to install a package.** On Debian or Ubuntu without `python3-venv`,
  `python3` cannot give an environment pip. When `requirements.txt` lists a package and the
  machine has neither `uv` nor `ensurepip`, `install.sh` and the update fetch
  [uv](https://docs.astral.sh/uv/) themselves — the official binary, at the version pinned
  in `environment.py`, its SHA-256 checked before it is unpacked — into
  `~/.local/share/ponos/uv`, without `sudo`, and install with it. Offline, the new version
  is not made, and the one in use carries on; the next check tries again. An environment
  whose Python a distribution upgrade took away (`.venv/bin/python` leading nowhere, or
  `pyvenv.cfg` naming an interpreter that is gone) is made again by the daemon's next check.
  `ponos doctor` has a *Python environment* line under *Machine* — there, its interpreter runs, and each
  package of `requirements.txt` imports — and when it is not, the command that mends it:
  `ponos update --environment`;
- **the page chooses nothing.** `POST /api/update` takes no command, no version and no
  path; it asks the remote again, under the lock, for the newest version of the configured
  channel. It answers only a request from this machine carrying the console's guard header
  and, from a browser, the console's own `Origin`. Opened from another machine, the dialog
  shows `ponos update` to copy instead — as it does when the app directory is not
  writable by the console.

The console restarts through its systemd unit when that is what started it, and replaces
its own process with the same command line otherwise.

`runner.auto_update = false` turns the automatic half off; `runner.update_interval_seconds`
changes the hour; `runner.update_channel` chooses between releases and `main` —
`ponos doctor` says which one is followed. An installation made from a local copy (`TR_SRC=.`) has no remote to
compare itself against: it says so once per check and carries on.

> **Requirements** — Linux or macOS, `python3` >= 3.11 (and `uv`, or `python3-venv` on
> Debian and Ubuntu: each version installs httpx, pydantic and cryptography, which the runner imports, and the
> console's FastAPI and uvicorn in a `.venv` of its own — see above), `git`,
> [Claude Code](https://claude.com/claude-code),
> and for pull requests either the GitHub App the console connects or `gh` authenticated.

| Variable | Effect |
| --- | --- |
| `TR_INTERVAL=10` | seconds between two runs (default: 1800, i.e. 30 min) |
| `TR_NO_SERVICE=1` | no daemon and no console: you run `ponos daemon` (or `ponos run`) yourself |
| `TR_NO_WEB=1` | the console's unit is installed, but left stopped |
| `TR_NO_OPEN=1` | the console is started, but not opened in the browser |
| `TR_SRC=.` | install from a local clone, without the network — and without self-updating |
| `TR_REF=main` | install the tip of `main` rather than the newest release, and follow every commit (`runner.update_channel = "main"`) |
| `TR_REF=v1.2` | install that tag rather than the newest release, and stay on it |

---

## Uninstall

```sh
curl -LsSf https://raw.githubusercontent.com/hermez-agency/ponos/main/uninstall.sh | sh
```

It takes back everything `install.sh` put down, on Linux and on a Mac: the Tailscale doors
first (`ponos tailscale disable`, while the binary is still there), then the systemd units
and their drop-ins (`~/.config/systemd/user/ponos*`), the launchd agents
(`~/Library/LaunchAgents/app.ponos.*.plist`, unloaded before they go), the console and the runner loop started
in the background where there was neither, the `ponos://` handler and its `xdg-mime`
association, the icons, the launcher and the installed versions.

`TR_PURGE=1` also removes the configuration, the logs and the history (`ponos.db`
included). Branches already pushed are never touched.
