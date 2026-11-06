"""The board as the issues of a GitHub repository.

An open issue carrying the `ponos` label is a ticket that is ready; the pull
request that answers it says `Closes #n`, and the issue is closed by GitHub when
it is merged. A team that follows its work in GitHub Issues has nothing to copy
into Notion — which is the whole of what this store is for.

Three decisions carry the rest of the module.

**It is a Markdown board with issues pulled into it.** `Board` already holds the
projects, the agents, the schedules and everything a run writes against a ticket
that GitHub has no column for — the runner's name, the cost, the session, the
pull request. An issue is mirrored into `tickets/` under an identifier made from
its repository and its number, and what GitHub *does* say — title, status, type,
sub-type, priority — is read from the issue on every pull and written back to it
on every `update`. Two copies of one fact, but the file never wins: GitHub is
the one that is edited by somebody else, so a pull overwrites what it names.

**The statuses are labels, and Ready is the absence of one.** `ponos:progress`,
`ponos:review`, `ponos:blocked`…, by the same word the `[notion]` status table
gives, minus the label: the ticket a person has just labelled `ponos` has no
status label yet, and that is what Ready is. Done is the issue closed. Moving a
ticket is one label taken off and one put on, never a rewrite of all of them —
the labels a team keeps for itself are none of this module's business.

**GitHub has no threads, and no bot user to tell the runner's voice by.** A
comment the runner writes opens on a hidden marker, and is read back as written
by `ponos`; everything else is its author's login. The whole issue is one
discussion, since that is what GitHub has — a comment under the runner's report
is an answer to it, which is the only reading that makes a « oui » to a
question work.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from . import git, resources, subtypes
from .files import Board
from .store import Comment, Missing, Page, StoreError, Unreachable, read

if TYPE_CHECKING:
    from .config import Issues as IssueSettings
    from .config import Notion

# What a comment of the runner's starts with: invisible on GitHub, and the only
# way to tell its words from those of the account it writes under — which is,
# more often than not, yours.
MARKER = "<!-- ponos -->"
VOICE = "ponos"

# The label that says a status, by its key in `config.STATUS` — without the
# word the label opens on. Ready has none: see the module docstring.
STATUS_LABELS = {
    "running": "progress",
    "review": "review",
    "validated": "validated",
    "blocked": "blocked",
    "paused": "paused",
    "cancelled": "cancelled",
    "done": "done",
}
# What a label of a status that GitHub knows nothing of is read as: `ponos:ready`
# is Ready, written or not.
READY_LABEL = "ready"

# How long a pull of the issues is believed. A pass asks for the ready column,
# the validated one and the blocked ones one after the other, and each of them
# would otherwise be a round of requests of its own.
FRESH = 8.0
# How many issues a pull goes back for because they left the open list — closed
# by a merge, unlabelled by somebody — rather than the whole history.
CHASING = 20
PAGE = 100
MAX_COMMENT = 60_000

_TYPE_LABELS = {f"type:{key}" for key in ("code", "writing", "external", "publication")}
_ISSUE_URL = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/issues/(\d+)")


def issue_id(repository: str, number: int) -> str:
    """The identifier of an issue as a page: 32 hexadecimal characters, like every page.

    The repository first and the number next, so that the issue can be found
    again from the identifier alone — `decode`, among the repositories the file
    names — and a last eight characters that differ from one issue to the next,
    since that is what a branch, a worktree and a log are named after.
    """
    name = repository.lower()
    head = hashlib.sha1(name.encode()).hexdigest()[:16]
    tail = hashlib.sha1(f"{name}#{number}".encode()).hexdigest()[:8]
    return f"{head}{number:08x}{tail}"


def closing(page: Page) -> str:
    """What a pull request's body says to close the issue this page is, or nothing."""
    issue = page.raw.get("issue")
    return f"Closes {issue['repository']}#{issue['number']}" if issue else ""


class Issues(Board):
    """A `store.Store` whose tickets are GitHub issues. See the module docstring."""

    def __init__(
        self,
        root: Path,
        settings: Notion | None,
        issues: IssueSettings,
        accounts: dict[str, str] | None = None,
    ) -> None:
        super().__init__(root, settings)
        self._issues = issues
        self._accounts = accounts or {}
        self._heads = {
            hashlib.sha1(name.lower().encode()).hexdigest()[:16]: name
            for name in issues.repositories
        }
        # The issue as GitHub last said it, by page: the labels a write starts
        # from, the body a brief is made of.
        self._seen: dict[str, dict[str, Any]] = {}
        self._pulled = 0.0
        self._projects: dict[str, str] = {}

    # -- talking to GitHub ---------------------------------------------------

    def call(self, repository: str, method: str, path: str, **fields: Any) -> Any:
        """One request of the REST API, through `gh` — and so through the same account,
        App or token that opens the pull requests (`git.token_for`)."""
        if not shutil.which("gh"):
            raise StoreError("gh not found — the issues of GitHub cannot be reached")
        command = ["gh", "api", "-X", method, f"repos/{repository}{'/' + path if path else ''}"]
        for name, value in fields.items():
            for one in value if isinstance(value, list) else [value]:
                command += ["-f", f"{name}{'[]' if isinstance(value, list) else ''}={one}"]
        result = git.run(command, timeout=60, token=git.token_for(repository, self._accounts))
        if not result.ok:
            message = (result.err or result.out).strip()
            if resources.network_error(message):
                raise Unreachable(f"GitHub: {message}")
            if "404" in message or "Not Found" in message:
                raise Missing(f"{repository}/{path}: {message}")
            raise StoreError(f"{repository}/{path}: {message}")
        try:
            return json.loads(result.out) if result.out.strip() else None
        except ValueError as error:
            raise StoreError(f"{repository}/{path}: GitHub did not answer in JSON") from error

    def _each(self, repository: str, path: str) -> list[dict[str, Any]]:
        """Every page of a list, until one comes back short."""
        found: list[dict[str, Any]] = []
        for number in range(1, 51):
            joined = "&" if "?" in path else "?"
            batch = self.call(repository, "GET", f"{path}{joined}per_page={PAGE}&page={number}")
            if not isinstance(batch, list):
                break
            found += batch
            if len(batch) < PAGE:
                break
        return found

    # -- what an issue is, as a page -----------------------------------------

    def _decode(self, page_id: str) -> tuple[str, int] | None:
        bare = page_id.replace("-", "")
        if len(bare) != 32 or bare[:16] not in self._heads:
            return None
        try:
            number = int(bare[16:24], 16)
        except ValueError:
            return None
        repository = self._heads[bare[:16]]
        return (repository, number) if issue_id(repository, number) == bare else None

    def _labels(self, issue: dict[str, Any]) -> set[str]:
        return {
            str(one.get("name", "") if isinstance(one, dict) else one)
            for one in issue.get("labels", [])
        }

    def _status(self, issue: dict[str, Any], labels: set[str]) -> str:
        """The status key of an issue: the label it carries, else open → ready, closed → done."""
        base = self._issues.label
        # Closed ends it, whatever label was left on it: a merge closes the issue
        # through `Closes #n` and nothing takes `ponos:review` off.
        if issue.get("state") == "closed":
            return "cancelled" if f"{base}:cancelled" in labels else "done"
        for key, word in STATUS_LABELS.items():
            if f"{base}:{word}" in labels:
                return key
        return "ready"

    def _derived(self, repository: str, issue: dict[str, Any]) -> dict[str, Any]:
        """What GitHub says of an issue, under the names the board spells its columns."""
        settings = self.settings()
        labels = self._labels(issue)
        values: dict[str, Any] = {
            "Name": str(issue.get("title", "")).strip(),
            settings.prop("status"): settings.state(self._status(issue, labels)),
            settings.prop("project"): [self._project(repository)],
            "Issue": issue.get("html_url", ""),
        }
        for label in sorted(labels & _TYPE_LABELS):
            values[settings.prop("type")] = settings.kind(label.split(":", 1)[1])
        for label in sorted(labels):
            if label.startswith("subtype:"):
                word = label.split(":", 1)[1]
                values[settings.prop("subtype")] = subtypes.option(subtypes.of(word)) or word
            elif label.startswith("priority:") and label.split(":", 1)[1].strip().isdigit():
                values[settings.prop("priority")] = min(int(label.split(":", 1)[1]), 100)
        return values

    def _project(self, repository: str) -> str:
        """The project page of a repository, made the first time it is wanted."""
        if repository not in self._projects:
            for page in super().query("projects"):
                if (read(page, "Repository") or "").lower() == repository.lower():
                    self._projects[repository] = page.id
                    break
            else:
                self._projects[repository] = super().create_row(
                    "projects", repository.rsplit("/", 1)[-1], {"Repository": repository}
                )
        return self._projects[repository]

    def _upsert(self, repository: str, issue: dict[str, Any]) -> str:
        """The issue written into `tickets/`, changed only where it is not already so."""
        page_id = issue_id(repository, int(issue["number"]))
        self._seen[page_id] = issue
        values = self._derived(repository, issue)
        try:
            current = super().page(page_id)
        except Missing:
            title = values.pop("Name")
            super().create_row("tickets", title, values, page_id=page_id)
            return page_id
        changed: dict[str, Any] = {}
        for name, value in values.items():
            now = current.title if name == "Name" else read(current, name)
            if isinstance(value, list):
                now = list(now or [])
            if now != value:
                changed[name] = value
        if changed:
            super().update("tickets", page_id, changed)
        return page_id

    def _pull(self, *, force: bool = False) -> None:
        """Every ready-to-work issue of every repository, brought up to date in `tickets/`."""
        if not force and time.monotonic() - self._pulled < FRESH:
            return
        seen: set[str] = set()
        label = quote(self._issues.label)
        for repository in self._issues.repositories:
            for issue in self._each(repository, f"issues?labels={label}&state=open"):
                if "pull_request" not in issue:
                    seen.add(self._upsert(repository, issue))
        # What left the open list — closed by a merge, put away by somebody — is
        # asked for by name, a few a pass: a ticket that never learns it is done
        # would sit in review for good.
        chased = 0
        for page in super().query("tickets"):
            ref = self._ref(page)
            if not ref or page.id in seen or chased >= CHASING:
                continue
            if read(page, self.settings().prop("status")) in (
                self.settings().state("done"),
                self.settings().state("cancelled"),
            ):
                continue
            chased += 1
            self._upsert(ref[0], self.call(ref[0], "GET", f"issues/{ref[1]}"))
        self._pulled = time.monotonic()

    def _ref(self, page: Page) -> tuple[str, int] | None:
        found = _ISSUE_URL.search(str(read(page, "Issue") or ""))
        if not found or found.group(1) not in self._issues.repositories:
            return None
        return found.group(1), int(found.group(2))

    def _issue(self, page_id: str, *, fresh: bool = False) -> tuple[str, dict[str, Any]] | None:
        """The issue a page is, as GitHub says it — None for a page that is not one."""
        decoded = self._decode(page_id)
        if decoded is None:
            return None
        key = issue_id(*decoded)
        if fresh or key not in self._seen:
            self._upsert(decoded[0], self.call(decoded[0], "GET", f"issues/{decoded[1]}"))
        return decoded[0], self._seen[key]

    def _page_of(self, collection: str, path: Path) -> Page:
        page = super()._page_of(collection, path)
        if ref := self._ref(page) if collection == "tickets" else None:
            page.raw["issue"] = {"repository": ref[0], "number": ref[1]}
            page.url = str(read(page, "Issue"))
        return page

    # -- reading -------------------------------------------------------------

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]:
        if self.resolve_database(database_id) == "tickets":
            self._pull()
        return super().query(database_id, filter_)

    def page(self, page_id: str) -> Page:
        if self._decode(page_id) is not None:
            self._issue(page_id, fresh=True)
        return super().page(page_id)

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        """The issue's body is the brief; what a run wrote on the file is the live report."""
        found = self._issue(block_id)
        if found is None:
            return super().blocks_text(block_id, depth, live=live)
        body = str(found[1].get("body") or "").strip()
        if not live:
            return body
        return f"{body}\n\n{super().blocks_text(block_id, depth, live=True)}".strip()

    def comments(self, page_id: str) -> list[Comment]:
        """The comments of the issue, as one discussion — GitHub has no threads."""
        decoded = self._decode(page_id)
        if decoded is None:
            return super().comments(page_id)
        found: list[Comment] = []
        for one in self._each(decoded[0], f"issues/{decoded[1]}/comments"):
            text = str(one.get("body") or "")
            ours = text.lstrip().startswith(MARKER)
            found.append(
                Comment(
                    text.lstrip().removeprefix(MARKER).strip() if ours else text.strip(),
                    str(one.get("created_at", "")),
                    id=str(one.get("id", "")),
                    discussion_id=page_id.replace("-", ""),
                    created_by=VOICE if ours else str((one.get("user") or {}).get("login", "")),
                )
            )
        return found

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        """Properties by name: GitHub's own go to GitHub, the rest to the file."""
        decoded = self._decode(page_id) if self.resolve_database(database_id) == "tickets" else None
        if decoded is not None and values:
            self._push(decoded, page_id, values)
        super().update(database_id, page_id, values)

    def _push(self, decoded: tuple[str, int], page_id: str, values: dict[str, Any]) -> None:
        settings = self.settings()
        repository, number = decoded
        issue = self._issue(page_id)
        assert issue is not None
        labels = self._labels(issue[1])
        base = self._issues.label
        add: list[str] = []
        drop: list[str] = []
        state = ""

        def swap(new: str, same: Callable[[str], bool]) -> None:
            drop.extend(name for name in labels if same(name) and name != new)
            if new and new not in labels:
                add.append(new)

        if (wanted := values.get(settings.prop("status"))) is not None:
            key = next((k for k in (*STATUS_LABELS, "ready") if settings.state(k) == wanted), "")
            if key:
                word = STATUS_LABELS.get(key, "")
                ours = {f"{base}:{one}" for one in (*STATUS_LABELS.values(), READY_LABEL)}
                swap(f"{base}:{word}" if word else "", ours.__contains__)
                state = "closed" if key in ("done", "cancelled") else "open"
        if (kind := values.get(settings.prop("type"))) is not None:
            key = settings.kind_of(str(kind))
            # Only the four the runner writes: a team's own `type:bug` is its own.
            swap(f"type:{key}" if key else "", _TYPE_LABELS.__contains__)
        if (sub := values.get(settings.prop("subtype"))) is not None:
            key = subtypes.of(sub)
            swap(f"subtype:{key}" if key else "", lambda name: name.startswith("subtype:"))
        if (score := values.get(settings.prop("priority"))) is not None:
            swap(f"priority:{int(score)}", lambda name: name.startswith("priority:"))
        for name in dict.fromkeys(drop):
            self.call(repository, "DELETE", f"issues/{number}/labels/{quote(name, safe='')}")
        if add:
            self.call(repository, "POST", f"issues/{number}/labels", labels=add)
        edit: dict[str, Any] = {}
        if state and state != issue[1].get("state"):
            edit["state"] = state
            if wanted == settings.state("cancelled"):
                edit["state_reason"] = "not_planned"
        if "Name" in values:
            edit["title"] = str(values["Name"])
        if edit:
            self.call(repository, "PATCH", f"issues/{number}", **edit)
        # What was just written is what the next write starts from.
        fresh = dict(issue[1])
        fresh["labels"] = sorted((labels - set(drop)) | set(add))
        fresh.update({k: v for k, v in edit.items() if k in ("state", "title")})
        self._seen[page_id.replace("-", "")] = fresh

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        decoded = self._decode(page_id)
        if decoded is None:
            return super().comment(page_id, text, discussion_id)
        body = f"{MARKER}\n{text}".strip()[:MAX_COMMENT]
        self.call(decoded[0], "POST", f"issues/{decoded[1]}/comments", body=body)

    def append_markdown(self, page_id: str, markdown: str) -> int:
        """What a run reports on its ticket is a comment of the issue."""
        if self._decode(page_id) is None:
            return super().append_markdown(page_id, markdown)
        self.comment(page_id, markdown.strip().removeprefix("---").strip())
        return 1

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        decoded = self._decode(page_id)
        if decoded is None:
            return super().replace_markdown(page_id, markdown)
        self.call(decoded[0], "PATCH", f"issues/{decoded[1]}", body=markdown.strip())
        self._seen.pop(page_id.replace("-", ""), None)
        return 1

    def trash(self, page_id: str) -> str:
        """An issue is never deleted: it is closed as not planned, which GitHub can undo."""
        if (decoded := self._decode(page_id)) is not None:
            self.call(
                decoded[0],
                "PATCH",
                f"issues/{decoded[1]}",
                state="closed",
                state_reason="not_planned",
            )
        return super().trash(page_id)
