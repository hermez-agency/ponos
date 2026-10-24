# Safety

[The guide](README.md) · [Ponos](../README.md)

What keeps a session away from what it should not touch.

## What protects your code

An agent working with nobody there to stop it needs a frame. Seven guardrails, all of
them on the program's normal path:

- **The main repository is never touched.** Every ticket gets a disposable `git worktree`
  on its own branch. Your working copy, your uncommitted files and your current branch
  stay exactly as you left them — and two tickets on the same project can move at once.
- **The agent commits, the runner publishes.** Pushing a branch and opening a PR are
  outward-facing gestures: they happen afterwards, once it is established that there are
  commits at all. A session that declares itself done without committing anything is
  blocked — unless the worktree is clean and its report says the work happened outside the
  repository (a Dokploy setting, a redeployment, a DNS record, tickets created in Notion):
  that ticket is *Done*, its report written into the page, since there was nothing to
  commit. Uncommitted changes, or a report saying it changed the code, still block it.
- **A session that stops without its report is asked for it, once.** No `ANSWER.md` on a
  ticket that needs one, or — on a code ticket — no commit, no change and no `RESULT`
  line: the runner picks the same conversation back up (`claude --resume`) and asks it for
  the account of what it did, and for nothing else. Only if that fails too is the ticket
  blocked, and a ticket is never picked up this way twice (`ponos.db` remembers it). A
  session that answered a question you asked in a comment — *what is X?* — and has nothing
  left to do ends `RESULT: ok`; one that still says `blocked` without asking anything, with
  its deliverable there, goes to *In review* rather than back to *Blocked*.
- **An ambiguous ticket is not guessed.** The prompt explicitly asks the agent to answer
  `RESULT: blocked` and stop rather than decide in your place. The ticket goes to the
  `blocked` status with the question in a comment — laid out by the runner, one line per
  idea: what is done (with its link), why it stops, then the question in one of three
  kinds the session chooses. **Yes-no** ends on `→ yes / no`; **choice** numbers two to
  four options on one line, so that `2`, *la 2* or the option's own words answer it;
  **free** is the question alone, saying what to give. The session hands these over as
  `DONE:`, `WHY:`, `QUESTION:`, `MODE:` and `OPTION:` lines before its `RESULT`; the
  checks and the logs stay in the folded block. However it arrives — in Notion, from
  Telegram or Slack, from the console — the answer reaches the next run with the
  question and the option it chose. A prompt file of your own that does not ask for these
  lines blocks as before, with its `RESULT` line as a free question.
- **A failing ticket takes only itself down.** The others in the same run carry on. Its
  worktree is kept for the post-mortem, and the session ID reopens the conversation
  exactly where it stopped: `claude --resume <id>`. The next attempt picks that same
  branch up — rebased onto the base branch first — rather than starting from nothing or
  refusing the ticket because the branch is there.
- **Answering a comment cannot change anything.** A conversation runs in the repository
  itself, but under `reply_permission_mode` — `plan` by default, which Claude Code cannot
  write from. Asking it a question in a comment can cost you a minute of its time and
  nothing else.
- **Two runs never overlap.** A file lock means a run that outlasts the timer's interval
  is not lapped by the next one.
- **A ticket is never stuck for good.** Because a run holds that lock, any ticket still
  marked *in progress* at the start of a run was abandoned — by a reboot, a
  `systemctl stop`, a crash. It goes back in the queue with a comment saying so, instead
  of sitting claimed forever, its *Progress* line emptied. Tickets claimed by another machine are left alone — which
  machine claimed one is the *Runner* column, and a board without it is taken to be run
  by a single machine: there, every ticket in progress no run is holding goes back.
  `ponos doctor` says which columns are missing and what each one switches off. One
  exception, and it is the point of the next guardrail: a ticket abandoned *mid
  publication* is never silently redone — it goes to *Blocked* asking whether the thing
  went out.
- **Nothing reaches the outside world without your column.** A merge, a post, an email:
  the runner does none of them until a human has moved that ticket to *Validated*. A
  session cannot put itself there, and no configuration key merges a pull request the way
  `open_pull_request` opens one.
- **A red job is never merged.** Before every merge the runner reads the pull request's
  checks: one that failed blocks the ticket (`merge.checks-failed`, the jobs named), one
  still running leaves it *Validated* for the next pass. That is the runner's own rule; the
  repository's is the **branch protection** on its base, which also stops a merge made by
  hand. On GitHub: *Settings → Branches → Add branch ruleset* (or classic protection) on
  `main`, *Require status checks to pass*, and pick the jobs of your CI — or from a
  terminal, with the names `gh pr checks` prints:

  ```sh
  gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input - <<'EOF'
  {"required_status_checks":{"strict":false,"contexts":["core (3.11)","quality"]},
   "enforce_admins":false,"required_pull_request_reviews":null,"restrictions":null}
  EOF
  ```

  This repository requires `core (3.11)`, `core (3.13)`, `quality`, `frontend` and `image`.

One thing to know: by default the runner starts the session with
`permission_mode = "bypassPermissions"`, because a session with nobody to ask cannot ask,
and would stall on the first test it needs to run. The isolation comes from the worktree,
not from the permission model. If you would rather have it the other way round,
`"acceptEdits"` forbids unapproved shell commands — at the cost of sessions that stop
often.

And one thing to weigh, if you use *Validated*. A publishing session runs under that same
permission mode, and its work is by definition **outward-facing**: it uses the credentials
that machine holds — an MCP server, a CLI already logged in, a key in the environment — to
post, send or deploy. The worktree protects your code; nothing protects an account the
machine can already write to. Which is why that session is started by one gesture and one
only, why it is told to publish what the page holds rather than to decide anything, and why
it is asked to stop rather than improvise when the tool it needs is missing. Read the
ticket before you validate it: validating is the trust boundary of this whole tool. If the
board is shared with people you would not hand those credentials to, leave the column out
— without it nothing in the runner reaches outside your repositories.
