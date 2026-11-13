"""What GitHub says of a pull request's checks, read through `gh`.

Apart from git.py, which keeps what a repository is on the machine — its
worktrees, its branches, the replay of one on another — and the few things
asked of GitHub about a pull request itself. The checks are another trade: a
verdict that arrives late, read again and again, run a second time when red,
compared with the base's own before blaming the pull request, and that GitHub
sometimes never even started.

The merge lives here too, and not by accident: nothing is merged while a job is
red or still running, so merging is the first thing that reads the checks. Kept
beside them, git.py has no reason to import this module, and this module reads
git.py's `run` and `token_for` through it — which is also where the tests
replace them. So are the open pull request of a branch and whether the base's
CI runs at push: reads of GitHub's side that no worktree has a part in.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import git

MERGE_FLAGS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}


class ChecksNotGreen(git.GitError):
    """A merge the runner itself refused: one of the pull request's jobs is not green.

    `state` is `failed` (a job is red) or `pending` (one is still running);
    `names` the jobs concerned.
    """

    def __init__(self, state: str, names: list[str]) -> None:
        self.state, self.names = state, names
        super().__init__(f"checks {state}: {', '.join(names) or '?'}")


def merge_pull_request(
    url: str, method: str = "squash", accounts: git.Accounts | None = None, signed: bool = True
) -> str:
    """Merge that pull request through `gh`. Returns what `gh` said of it.

    The one outward-facing gesture the runner makes on its own — and it makes it
    only because it was asked twice: once by the ticket having a pull request at
    all, once by somebody moving that ticket into the validated column. Anything
    GitHub refuses — a conflict, a check still red, a review still required — is
    raised as it came, because the wording is the answer.

    `--auto` is deliberately not used: a merge that lands quietly twenty minutes
    later, when a check goes green, is a merge nobody watched.

    Nothing is merged while a job is red or still running, whoever asks and
    whatever GitHub would have allowed: a repository whose branch is not
    protected would let it through — that is how #326 landed with its frontend
    job red. A job GitHub cannot be asked about is not read as red.

    `signed` false is `[claude] attribution` off: a squash whose commit would
    carry Claude Code's signature is given its message without it — see
    `squash_body`.
    """
    if not shutil.which("gh"):
        raise git.GitError("gh not found — cannot merge the pull request")
    listed = checks(url, accounts)
    if red := sorted(
        {str(one.get("name") or "") for one in listed if one.get("bucket") in ("fail", "cancel")}
    ):
        raise ChecksNotGreen("failed", red)
    if running := sorted(
        {str(one.get("name") or "") for one in listed if one.get("bucket") == "pending"}
    ):
        raise ChecksNotGreen("pending", running)
    flag = MERGE_FLAGS.get(method, "--squash")
    body = squash_body(url, accounts) if flag == "--squash" and not signed else None
    result = git.run(
        ["gh", "pr", "merge", url, flag, *(["--body", body] if body is not None else [])],
        timeout=300,
        token=git.token_for(url, accounts),
    )
    if result.ok:
        return (result.out or f"merged ({method})").strip()
    raise git.GitError(f"gh pr merge: {result.err or result.out}")


def squash_body(url: str, accounts: git.Accounts | None = None) -> str | None:
    """The body GitHub would give that pull request's squash commit, unsigned — or None.

    None when it has nothing to lose — no `Co-Authored-By` of Claude's, no
    « Generated with Claude Code » —, or when it could not be read: GitHub then
    writes its own, as it always did. The repository says which body it writes
    (`squash_merge_commit_message`): the pull request's description, none, or
    by default the commits' messages — the one commit's body, or each commit
    as a `* ` item when there are several.
    """
    token = git.token_for(url, accounts)
    view = git.run(["gh", "pr", "view", url, "--json", "body,commits"], timeout=60, token=token)
    try:
        pull = json.loads(view.out) if view.ok else {}
    except ValueError:
        pull = {}
    if not isinstance(pull, dict) or not pull:
        return None
    setting = "COMMIT_MESSAGES"
    if found := re.match(r"https?://github\.com/([^/]+/[^/]+)/pull/", url):
        asked = git.run(
            ["gh", "api", f"repos/{found.group(1)}", "--jq", ".squash_merge_commit_message"],
            timeout=60,
            token=token,
        )
        setting = asked.out.strip() if asked.ok and asked.out.strip() else setting
    if setting == "BLANK":
        return None
    if setting == "PR_BODY":
        said = str(pull.get("body") or "")
    else:
        commits = [one for one in pull.get("commits") or [] if isinstance(one, dict)]
        if len(commits) == 1:
            said = str(commits[0].get("messageBody") or "")
        else:
            said = "\n\n".join(
                f"* {one.get('messageHeadline') or ''}"
                + (f"\n\n{body}" if (body := str(one.get("messageBody") or "").strip()) else "")
                for one in commits
            )
    cleaned = git.unsigned(said)
    return cleaned if cleaned != said else None


# How long a pull request's checks are given to appear after a push: GitHub
# registers them a few seconds after the commit arrives, and asking at once
# would read a repository with CI as one without.
CHECKS_APPEAR_SECONDS = 60


def wait_for_checks(
    url: str, worktree: Path, minutes: int, accounts: git.Accounts | None = None
) -> str:
    """Wait for the pull request's checks: `passed`, `failed`, `pending` or `none`.

    `none` without asking anybody when the repository has no workflow of its
    own, which is most of the ones that have no CI — and when `minutes` is
    zero, which says not to wait. `pending` is the time it was given running
    out: the merge is asked all the same, and GitHub refuses it if a check it
    requires is not green.
    """
    if minutes <= 0 or not shutil.which("gh"):
        return "none"
    if not (Path(worktree) / ".github" / "workflows").is_dir():
        return "none"
    token = git.token_for(url, accounts)
    deadline = time.monotonic() + minutes * 60
    appear_by = time.monotonic() + CHECKS_APPEAR_SECONDS
    while True:
        left = int(deadline - time.monotonic())
        if left <= 0:
            return "pending"
        result = git.run(
            ["gh", "pr", "checks", url, "--watch", "--interval", "20"],
            timeout=left,
            token=token,
        )
        said = f"{result.out}\n{result.err}".lower()
        if result.ok:
            return "passed"
        if result.code == git.TIMED_OUT:
            return "pending"
        if "no checks reported" in said:
            if time.monotonic() >= appear_by:
                return "none"
            time.sleep(10)
            continue
        return "failed"


# What a red check is still given after it has been asked to run again, before
# its pull request's checks are read: GitHub puts the jobs back in the queue a
# moment after the call returns, and reading at once would read the old verdict.
RERUN_SETTLE_SECONDS = 20


def checks(
    url: str, accounts: git.Accounts | None = None, timeout: int = 60
) -> list[dict[str, Any]]:
    """The pull request's checks, as `gh pr checks --json` lists them.

    Read whatever the exit code: `gh` answers 1 when a check failed, and the
    list it printed is the very thing asked for. Nothing when it cannot say —
    a `gh` too old for `--json`, no network — which the caller reads as not
    knowing, never as green.
    """
    if not shutil.which("gh"):
        return []
    result = git.run(
        ["gh", "pr", "checks", url, "--json", "name,bucket,link"],
        timeout=timeout,
        token=git.token_for(url, accounts),
    )
    if "unknown flag" in f"{result.err}\n{result.out}":
        return _rolled_up(url, accounts, timeout)
    try:
        listed = json.loads(result.out or "[]")
    except ValueError:
        return []
    if not isinstance(listed, list):
        return []
    return [one for one in listed if isinstance(one, dict)]


# How `gh pr checks` sorts what GitHub says of a check into its buckets, for the
# gh too old to be asked for them. Anything not named here is still running.
_BUCKETS = {
    "SUCCESS": "pass",
    "SKIPPED": "skipping",
    "NEUTRAL": "skipping",
    "FAILURE": "fail",
    "ERROR": "fail",
    "TIMED_OUT": "fail",
    "ACTION_REQUIRED": "fail",
    "STARTUP_FAILURE": "fail",
    "CANCELLED": "cancel",
}


def _rolled_up(
    url: str, accounts: git.Accounts | None = None, timeout: int = 60
) -> list[dict[str, Any]]:
    """The checks of a pull request, for a `gh` that has no `pr checks --json`.

    `--json` came to `gh pr checks` in 2.48, and Ubuntu ships 2.46: on such a
    machine every check read as unknown — no names, nothing run again, no
    comparison with the base — and a forced merge stopped on a red it could not
    say anything about. `gh pr view --json statusCheckRollup` is far older, and
    says the same things in GitHub's own words, sorted here as `gh` sorts them.
    """
    result = git.run(
        ["gh", "pr", "view", url, "--json", "statusCheckRollup"],
        timeout=timeout,
        token=git.token_for(url, accounts),
    )
    try:
        rollup = json.loads(result.out or "{}").get("statusCheckRollup") if result.ok else None
    except (ValueError, AttributeError):
        return []
    listed = []
    for one in rollup if isinstance(rollup, list) else []:
        if not isinstance(one, dict):
            continue
        if one.get("__typename") == "StatusContext":
            name, link, verdict = one.get("context"), one.get("targetUrl"), one.get("state")
        else:
            name, link = one.get("name"), one.get("detailsUrl")
            verdict = one.get("conclusion") if one.get("status") == "COMPLETED" else ""
        listed.append(
            {
                "name": str(name or ""),
                "bucket": _BUCKETS.get(str(verdict or "").upper(), "pending"),
                "link": str(link or ""),
            }
        )
    return listed


def _failing(url: str, accounts: git.Accounts | None = None) -> list[dict[str, Any]]:
    """The pull request's checks that failed — see `checks`."""
    return [one for one in checks(url, accounts) if one.get("bucket") in ("fail", "cancel")]


def failing_checks(url: str, accounts: git.Accounts | None = None) -> list[str]:
    """The names of the pull request's checks that failed, or nothing when unknown."""
    return sorted({str(one.get("name") or "") for one in _failing(url, accounts)} - {""})


def unstarted_checks(url: str, accounts: git.Accounts | None = None) -> str:
    """Why GitHub never started the pull request's red jobs — or "" when they ran.

    A job GitHub refuses to start — an account whose payment failed, a
    spending limit reached — is red in two seconds, exactly like a test that
    failed. It says nothing about the code, and nothing a session or a second
    run could change: what does is in the annotation GitHub leaves on it, which
    is returned as it is written. Only when *every* red check is such a job: one
    that did run and failed is the code's red, and is read as such.
    """
    failing = _failing(url, accounts)
    parts = git.reference_parts(url)
    if not failing or len(parts) < 3:
        return ""
    host, owner_name = parts[0], "/".join(parts[1:3])
    token = git.token_for(url, accounts)
    reasons = []
    for one in failing:
        job = re.search(r"/actions/runs/\d+/job/(\d+)", str(one.get("link") or ""))
        if not job:
            return ""
        result = git.run(
            [
                "gh",
                "api",
                "--hostname",
                host,
                f"repos/{owner_name}/check-runs/{job.group(1)}/annotations",
                "-q",
                ".[].message",
            ],
            timeout=60,
            token=token,
        )
        said = (
            next(
                (line.strip() for line in result.out.splitlines() if "was not started" in line),
                "",
            )
            if result.ok
            else ""
        )
        if not said:
            return ""
        reasons.append(said)
    return reasons[0]


def rerun_failed_checks(url: str, accounts: git.Accounts | None = None) -> bool:
    """Run the failed jobs of the pull request's workflows again. Whether any was.

    Only GitHub Actions can be asked: a check another app posts has no run to
    start again, and is left as it is. Only the failed jobs, too — the green
    ones already said what they had to say, and running them again would only
    spend minutes.
    """
    parts = git.reference_parts(url)
    runs = sorted(
        {
            found.group(1)
            for one in _failing(url, accounts)
            if (found := re.search(r"/actions/runs/(\d+)", str(one.get("link") or "")))
        }
    )
    if not runs or len(parts) < 3:
        return False
    repository = "/".join(parts[:3])
    token = git.token_for(url, accounts)
    started = [
        git.run(
            ["gh", "run", "rerun", one, "--failed", "-R", repository], timeout=60, token=token
        ).ok
        for one in runs
    ]
    if any(started):
        time.sleep(RERUN_SETTLE_SECONDS)
    return any(started)


def failed_log(url: str, accounts: git.Accounts | None = None, most: int = 6000) -> str:
    """The end of the log of the pull request's failed jobs, or nothing when unknown.

    `gh run view --log-failed`, one run after the other, each cut to its tail:
    what went wrong is at the end of a log, and the beginning of one is a
    hundred lines of setup that would only crowd the prompt of the session
    reading it. `most` is for all the runs together.
    """
    parts = git.reference_parts(url)
    runs = sorted(
        {
            found.group(1)
            for one in _failing(url, accounts)
            if (found := re.search(r"/actions/runs/(\d+)", str(one.get("link") or "")))
        }
    )
    if not runs or len(parts) < 3:
        return ""
    token = git.token_for(url, accounts)
    logs = []
    for one in runs:
        result = git.run(
            ["gh", "run", "view", one, "--log-failed", "-R", "/".join(parts[:3])],
            timeout=120,
            token=token,
        )
        if result.ok and result.out.strip():
            logs.append(result.out.strip()[-(most // len(runs)) :])
    return "\n\n".join(logs)


def base_failures(
    url: str, base: str, accounts: git.Accounts | None = None
) -> list[tuple[str, str]]:
    """The checks that failed on the newest commit of `base`, with the page of each run.

    What tells a pull request that broke something from one that merely
    inherited a red `main`: the same check red on both is not the pull
    request's doing. Nothing when it cannot be asked, which leaves the red to
    the pull request — the cautious reading. The link is the run to open
    first when the base has to be repaired.
    """
    parts = git.reference_parts(url)
    if not base or len(parts) < 3 or not shutil.which("gh"):
        return []
    host, owner_name = parts[0], "/".join(parts[1:3])
    result = git.run(
        [
            "gh",
            "api",
            "--hostname",
            host,
            f"repos/{owner_name}/commits/{base}/check-runs?per_page=100",
            "-q",
            '.check_runs[] | select(.conclusion == "failure" or .conclusion == '
            '"timed_out" or .conclusion == "cancelled") | [.name, .html_url] | @tsv',
        ],
        timeout=60,
        token=git.token_for(url, accounts),
    )
    if not result.ok:
        return []
    found: dict[str, str] = {}
    for line in result.out.splitlines():
        name, _, link = line.strip().partition("\t")
        if name:
            found.setdefault(name, link)
    return sorted(found.items())


def failing_on(url: str, base: str, accounts: git.Accounts | None = None) -> list[str]:
    """The names of the checks that failed on the newest commit of `base`."""
    return [name for name, _ in base_failures(url, base, accounts)]


def ci_at_push(repo: Path, base: str, accounts: git.Accounts | None = None) -> str:
    """Does the CI of that repository run when something is pushed to `base`?

    `ran` when at least one push run of the branch did something, `none` when
    it has no push run at all, `skipped` when every one it has was skipped — the
    two shapes of a base nobody watches, which is how a red one goes unseen.
    Nothing when it cannot be asked: no `gh`, no remote on GitHub, no network.
    """
    remote = git.remote_url(repo)
    parts = git.reference_parts(remote)
    if not base or len(parts) < 3 or not shutil.which("gh"):
        return ""
    result = git.run(
        [
            "gh",
            "run",
            "list",
            "--branch",
            base,
            "--event",
            "push",
            "--limit",
            "20",
            "--json",
            "conclusion",
            "-R",
            "/".join(parts[:3]),
        ],
        timeout=60,
        token=git.token_for(remote, accounts),
    )
    try:
        runs = json.loads(result.out or "[]") if result.ok else None
    except ValueError:
        runs = None
    if not isinstance(runs, list):
        return ""
    if not runs:
        return "none"
    worked = any(one.get("conclusion") != "skipped" for one in runs if isinstance(one, dict))
    return "ran" if worked else "skipped"


def pull_request_on(repo: Path, branch: str, accounts: git.Accounts | None = None) -> str:
    """The URL of an open pull request made from that branch, or nothing.

    Nothing also means the question could not be asked — `gh` missing, not
    authenticated, no network. That is deliberately not distinguished here: this
    is never the only thing a caller looks at before touching a branch.
    """
    if not shutil.which("gh"):
        return ""
    result = git.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            "-q",
            ".[0].url",
        ],
        cwd=repo,
        timeout=60,
        token=git.token_for(git.remote_url(repo), accounts),
    )
    return result.out if result.ok else ""
