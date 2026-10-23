"""What the API answers, said once, for the OpenAPI schema the page's types come from.

`frontend/src/lib/types.ts` used to be these shapes copied by hand from the
dictionaries `api.py`, `console.py` and `live.py` build: a key renamed here
broke nothing before the browser. The routes now name the shape they answer
(`response_model=`), FastAPI writes it into `/openapi.json`, and `npm run
types` turns that into `frontend/src/lib/api-types.d.ts` — which the CI
regenerates, and refuses when it differs from the one committed.

These models describe; they do not check. A route answers the dictionary it
built, masked (`routes.answer`), and FastAPI never sees it go: a route that
returns a `Response` is not validated against its `response_model`. What
keeps the two honest is that both are written here, side by side with the
code that builds the answer — and that the page is typed by them.

Three choices, each against the obvious one:

- **Models, not `TypedDict`s.** A `TypedDict` says "a dictionary" better, but
  Pydantic refuses `typing.TypedDict` before Python 3.12, and the one it
  takes instead is a package the core has not asked for.
- **`omitted()` for a key that may be absent.** A field with a default is
  optional, but its default is written into the schema, where
  `openapi-typescript` reads it as "always there". The page has always told a
  key that may be missing from one that may be null: `omitted()` leaves the
  key out of `required` and its default out of the schema.
- **The docstring under a field is its description.** It is what the page
  reads as the comment over the property, as it read the one over each line
  of `types.ts`.

The literal types — the columns, the roles, the kinds of a field — have no
name of their own in the schema: the page takes them from the field they
type (`Ticket["column"]`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict


def _undefaulted(schema: JsonDict) -> None:
    schema.pop("default", None)


def omitted(**field: Any) -> Any:
    """A key the answer may leave out: see the module's docstring."""
    return Field(default=None, json_schema_extra=_undefaulted, **field)


class Shape(BaseModel):
    """One shape the API answers in."""

    # `model` and `model_label` are what the page has always read: the
    # namespace Pydantic keeps for itself is not the API's concern.
    model_config = ConfigDict(use_attribute_docstrings=True, protected_namespaces=())


ColumnKey = Literal[
    "draft",
    "ready",
    "running",
    "blocked",
    "paused",
    "review",
    "validated",
    "failed",
    "done",
    "cancelled",
]
TicketKind = Literal["code", "publication", "writing", "external"]
IdeaStatus = Literal["proposed", "kept", "discarded", "ticket"]
UpgradePhase = Literal[
    "idle", "waiting", "downloading", "installing", "restarting", "done", "failed"
]


# -- the board -----------------------------------------------------------------


class Picture(Shape):
    """One of a project's two pictures, as the console draws it.

    `src` is the console's own address for the image, never the board's: a
    file Notion keeps is behind a URL that is dead within the hour, so the
    server keeps a copy and serves that.
    """

    kind: Literal["image", "emoji", ""]
    src: str = omitted()
    emoji: str = omitted()
    url: str = omitted()
    """The address a pasted picture lives at — somebody else's, so not a secret."""
    pending: bool = omitted()
    """Chosen here, and not yet taken by the board."""
    error: str = omitted()
    """Why the board did not take it — it is tried again at the next reading."""
    conflict: Literal["notion", "console", ""] = omitted()
    """Changed on both sides between two readings: which side's picture won."""


class Words(Shape):
    en: str
    fr: str


class Block(Shape):
    """Why a ticket stopped, as `blocks.py` describes it — its words in both languages."""

    code: str
    family: Literal["merge", "session", "infrastructure", "question", "access"]
    """The family the cause belongs to, drawn with its icon."""
    who: Literal["ponos", "user", "external"]
    """Who has to move: Ponos, you, or something outside both."""
    action: Literal["retry", "answer", "clean", "base-ci", "open-pr"]
    """What a stopped card offers: run it again, answer, clean, the base's CI, the pull request."""
    policy: str
    """What the runner may do on its own: `retry:n`, `wait-base` or `ask`."""
    label: Words
    help: Words


class Check(Shape):
    name: str
    bucket: str
    link: str


class Ci(Shape):
    """A pull request's checks as the runner last read them: stored, never fetched with the
    board."""

    state: Literal["pending", "passed", "failed"]
    label: str
    """The board's word for it (« en cours », « réussi », « erreur »)."""
    checks: list[Check]
    """`gh pr checks` buckets: pass, fail, pending, skipping, cancel."""
    link: str
    """GitHub's page listing the checks."""


class Held(Shape):
    reason: str
    detail: str


class Phase(Shape):
    """What a ticket in progress is going through, as the runner last wrote it — see
    `state.enter`."""

    key: Literal["starting", "session", "rebase", "local-ci", "checks", "repair", "resolve"]
    detail: str
    """The base for a rebase or a resolution, the command for the local CI, the pull request for
    its checks or their repair."""
    since: str
    """When it began, ISO 8601 in UTC."""


class WorkTime(Shape):
    """`worktime` on a ticket: how long Ponos worked on it — see `worktime.py`."""

    work: float
    """Seconds of work, as of the moment the ticket was read."""
    paused: float
    """Seconds waited on a question, a block or credit."""
    sessions: int
    running: bool
    """Whether a session is working on it now: the clock goes."""
    pause: Literal["", "question", "blocked", "credit"]
    """Why the clock is stopped, if it is: `question`, `blocked` or `credit`."""


class Ticket(Shape):
    id: str
    short: str
    title: str
    url: str
    status: str
    column: ColumnKey
    project: str
    project_id: str = omitted()
    """The project's page id, empty for a ticket without one."""
    project_icon: Picture = omitted()
    """The project's icon, as `Project.icon` is: emoji, image or empty."""
    goal: str = omitted()
    """The name of the goal it serves, empty for a ticket that serves none — see `goals.py`."""
    goal_id: str = omitted()
    """That goal's page id, empty with it."""
    kind: str
    """The project's kind of work, `code` or `document`."""
    type: str
    """The ticket's own type, as the board spells it: Code, Writing, External action…"""
    priority: int | None
    """A score from 0 to 100, an empty cell read as 50; null on a board without the column."""
    model: str
    model_label: str = omitted()
    """`model` as `provider/model` — claude/haiku, deepseek/r1 — said by `models.label`."""
    progress: str
    runner: str
    pull_request: str
    session: str
    session_link: str
    cost: float | None
    duration: float | None
    scheduled: str
    created: str
    edited: str
    """Notion's `last_edited_time`: when a done ticket closed, where the runner's history does not
    say."""
    sync: Literal["pending", "failed", "conflict"] = omitted()
    """A move that has not reached Notion: on its way, refused, or not made
    because Notion had been changed meanwhile — see `web/board.py`."""
    sync_error: str = omitted()
    """Why, when it is not on its way."""
    sync_status: str = omitted()
    """The status the move was to."""
    held: Held = omitted()
    """On a ready card only: why it is still there — see `held` in `web/board.py`."""
    block: Block | None = omitted()
    """On a blocked or failed card only: why it stopped — see `blocks.py`."""
    ci: Ci | None = omitted()
    """In review with a pull request that has checks only: where they stand — see `ci.py`."""
    phase: Phase | None = omitted()
    """In progress only: what it is going through now, and since when — null when the runner
    wrote nothing about it."""
    subtype: str = omitted()
    """A code ticket's sub-type, by its key — `bug`, `docs` — or empty: see `subtypes.py`."""
    worktime: WorkTime | None = omitted()
    """How long Ponos worked on it, the clock stopped while it waited — null when no run was made:
    see `worktime.py`."""


class ModelInUse(Shape):
    label: str
    full: str
    default: bool


class TicketDetail(Ticket):
    """A ticket, with the page under it: the brief, the report, the notes between."""

    content: str
    """The page's blocks, flattened the way the runner reads them."""
    model_in_use: ModelInUse = omitted()
    """The model it runs on: the last session's own word, then the column, then the defaults."""
    on: str = omitted()
    """The prompt run at every change of the ticket's status, empty for none."""


class Subtype(Shape):
    """One sub-type of a code ticket, whole, as the board sends the table of them."""

    key: str
    option: str
    """How the board writes it: « Amélioration », « Sécurité »."""
    label: str
    """The developers' word — « Feature », « Security » — shown as it is in
    every language: a sub-type is never translated, see `SUBTYPES` in subtypes.py."""
    commit: str
    """The prefix of its commits: `fix`, `feat`…"""
    changelog: str
    """Its CHANGELOG section, empty for none."""


class Column(Shape):
    key: ColumnKey
    name: str


class Choice(Shape):
    value: str
    label: str


class TicketChoices(Shape):
    type: list[Choice] = omitted()
    model: list[Choice] = omitted()
    subtype: list[Choice] = omitted()
    goal: list[Choice] = omitted()
    """The goals a new ticket may serve: only on a board with the column, and goals to point at."""


class Board(Shape):
    tickets: list[Ticket]
    validates: bool = omitted(alias="validate")
    """Whether this board has a `validated` column the runner would honour."""
    cancel: bool = omitted()
    """Whether this board has a `cancelled` column to give a ticket up in."""
    columns: list[Column]
    choices: TicketChoices = omitted()
    """What a new ticket may be given beside its title, for the columns this
    board has: a column it lacks is not a key here."""
    priority: bool = omitted()
    """Whether this board has a priority column to write a score in."""
    subtypes: list[Subtype] = omitted()
    """The sub-types of a code ticket, in the order they are offered."""
    model: str = omitted()
    """What a ticket with no model of its own runs on: `runner.model`, empty for Claude Code's
    own."""
    places: int = omitted()
    """How many tickets the runner takes at once: `runner.max_concurrent`, what the
    column of work in flight is counted against."""
    version: int = omitted()
    """Which board the stream sent, for the changes that follow it."""


class Changed(Shape):
    after: str
    ticket: Ticket


class BoardChanges(Shape):
    """What moved on the board since version `base`, as the stream sends it."""

    base: int
    version: int
    changed: list[Changed]
    """Changed or new, each with the ticket it now follows (`""`: the first)."""
    removed: list[str]


class Transition(Shape):
    """One change of status met on a ticket that carries an « On » prompt, and what running it
    did."""

    id: int
    old: str
    new: str
    depth: int
    """How many generations of tickets created by an execution it is below a person's."""
    state: str
    """`pending`, `running`, `ok`, `failed` or `skipped`."""
    seen_at: str
    started_at: str
    ended_at: str
    cost_usd: float | None
    seconds: float | None
    session: str
    result: str
    """What the session said, or why it did not run."""


class Transitions(Shape):
    transitions: list[Transition]


class TicketCreated(Shape):
    """A ticket written on the board: its page, and the title it was given."""

    id: str
    title: str


class TicketOn(Shape):
    id: str
    on: str
    """The prompt now run at every change of status, empty once removed."""


class Moved(Shape):
    """A move queued for the board: the status it goes to."""

    id: str
    status: str
    """The status as the board spells it."""
    sync: Literal["pending"] = omitted()
    """On its way to Notion, and not there yet: see `web/board.py`."""


# -- projects ------------------------------------------------------------------


class Project(Shape):
    id: str
    """Empty for a project the configuration names and the board has never heard of."""
    name: str
    kind: str
    url: str
    repository: str = omitted()
    """What the project page declares, when it declares anything."""
    path: str = omitted()
    description: str = omitted()
    """What it does, in a sentence, and its public address — the page's columns, empty when it has
    none."""
    site: str = omitted()
    configured: str = omitted()
    """The `[projects]` entry of the configuration, where there is one."""
    located: str = omitted()
    """Where the clone really is on this machine — said only by the project's own page, empty when
    there is none."""
    source: Literal["board", "config"] = omitted()
    """Where this row came from: the board, or the file on this machine."""
    cover: Picture = omitted()
    """The banner of its page, and the mark in front of its name. See `Picture`."""
    icon: Picture = omitted()


class ProjectCheck(Shape):
    """What a repository and a folder turn out to be, asked while a new project is written."""

    repository: str = omitted()
    """The repository as it will be kept: `https://github.com/owner/name`."""
    cloned: str = omitted()
    """Where this machine already has its clone; empty, it is cloned at the first ticket."""
    repository_error: str = omitted()
    path: str = omitted()
    origin: str = omitted()
    """The folder's `origin` remote — a GitHub address when it is GitHub's."""
    path_error: str = omitted()


class Pictures(Shape):
    """What a picture's change answers: both pictures of the project, as they now are."""

    id: str
    cover: Picture
    icon: Picture


class ProjectDetail(Project):
    """One project, opened: the row, and what is written on its page."""

    content: str
    version: str


class ProjectBrief(Shape):
    """A project's brief as the editor opens it, and what saving it would not keep."""

    content: str
    version: str
    """What `saveProject` is handed back as `base`: refused if the page no longer says it."""
    losses: dict[str, int]
    """The kinds of Notion content Markdown cannot hold, and how many of each."""


class ValidationField(Shape):
    """One switch of the automatic validation, worded as the global card words it."""

    kind: TicketKind
    name: str
    """The global setting's key, `runner.force_validated_code`."""
    label: str
    help: str


class ByKind(Shape):
    """One switch for each of the four types of ticket."""

    code: bool
    publication: bool
    writing: bool
    external: bool


class Validation(Shape):
    own: bool
    """Whether the project has its own switches; false, the file's apply."""
    values: ByKind
    """What applies to its tickets: its own switches, or the file's."""
    global_: ByKind = Field(alias="global")
    """The file's, whatever the project says."""
    fields: list[ValidationField]


class ProjectIdeas(Shape):
    """Whether ideas are found for a project on a schedule — see idea_schedule.py."""

    enabled: bool
    """What applies to it: its own word, or the file's."""
    own: bool
    """Whether the project says so itself, against the file saying for it."""
    schedule: str
    """`runner.ideas_schedule`, so the page can say that nothing is scheduled at all."""


class ProjectLocalCi(Shape):
    """Whether a project's CI runs on this machine before its pull request — see local_ci.py."""

    enabled: bool
    """What applies to it: its own word, or the file's."""
    own: bool
    """Whether the project says so itself, against `runner.local_ci` saying for it."""
    global_: bool = Field(alias="global")
    """`runner.local_ci`, whatever the project says."""
    command: str
    """What runs its CI; empty, its GitHub workflows through `act` when it is installed."""
    docker: bool
    """Whether Docker answers on this machine."""
    unavailable: str
    """Why it cannot be turned on here, or empty when it can."""


class ProjectSettings(Shape):
    """What a project decides for itself — see project_settings.py."""

    id: str
    validation: Validation
    ideas: ProjectIdeas
    local_ci: ProjectLocalCi


class ProjectDeleted(Shape):
    """What deleting a project did, as the server counts it."""

    id: str
    name: str
    url: str
    """Where the page can be restored from; empty on a board of files."""
    tickets: int
    blocked: int
    trashed: int


class Projects(Shape):
    projects: list[Project]
    workspace_root: str
    storage: str
    """`storage.mode`: which board these came off."""


class Context(Shape):
    """The standing context: what reaches every ticket before the ticket itself."""

    text: str
    page: str
    """The page it is written on, "" where the workspace has none."""
    where: str
    """What that page is called, for the sentence that says it is missing."""
    storage: str
    editable: bool


class ContextSaved(Shape):
    ok: bool
    text: str
    """What the page now says, trimmed."""


# -- schedules -----------------------------------------------------------------


class Schedule(Shape):
    """One row of the Schedules database: a recipe for a ticket, and how often it is born."""

    id: str
    name: str
    url: str
    cadence: str
    """"Hourly" | "Daily" | "Weekly" | "Monthly", or empty where nobody picked one."""
    at: str
    day: str
    active: bool
    next: str
    """When the next ticket is due, and when the last one was made. Empty for "never yet"."""
    last: str
    ticket: str
    """The ticket the last occurrence made, addressed as the board addresses one."""
    project: str
    """The project's name, when the server already knew it; the page it points at, always."""
    project_id: str
    model: str
    priority: int | None
    """A score from 0 to 100, null when the schedule says none: its tickets are born at 50."""
    type: str = omitted()
    """What its tickets are born as, by their keys — `code`, `bug` — empty to let them be
    guessed."""
    subtype: str = omitted()
    problem: str
    """What stops this schedule being acted on, in the words `doctor` prints."""


class ScheduleDetail(Schedule):
    """One schedule opened: the row, and its page body — the brief of every ticket it makes."""

    body: str


class ScheduleSaved(Shape):
    id: str


class ScheduleNamed(Shape):
    """A schedule created, or taken off the board: its row, and what it was called."""

    id: str
    name: str


class ScheduleLaunched(Shape):
    """The ticket a schedule launched by hand was born as."""

    ticket: str
    title: str


class ScheduleChoices(Shape):
    type: list[Choice] = omitted()
    subtype: list[Choice] = omitted()


class IdeasCalendar(Shape):
    """The scheduled search for ideas, as the recurrences' calendar draws it: read only."""

    active: bool
    next: str
    """The next pass, ISO 8601 to the minute; empty when none is due."""
    last: str
    upcoming: list[str]
    """The passes to come, the next ones first."""


class Schedules(Shape):
    enabled: bool
    """`runner.schedule`: off, and nothing is born however the rows are ticked."""
    database: bool
    """Whether the workspace has a Schedules database at all."""
    timezone: str = omitted()
    """The zone the hours are said in (the runner's), for the calendar to lay them out in; empty
    when unknown."""
    page: str
    """What that page is called, for the sentence that says it is missing."""
    storage: str = omitted()
    """`storage.mode`: which board these came off."""
    schedules: list[Schedule]
    choices: ScheduleChoices = omitted()
    """What the form offers for the type and the sub-type: only the columns the database has."""
    ideas_pass: IdeasCalendar


class ScheduleTicket(Shape):
    """One ticket a schedule made, as its page lists it."""

    id: str
    short: str
    title: str
    url: str
    status: str
    column: ColumnKey
    created: str
    cost: float | None
    duration: float | None
    """In minutes, as on a card."""
    pull_request: str
    linked: Literal["recorded", "title"]
    """How it is known to be this schedule's: by its id, or by its title and its date alone —
    see `web/lineage.py`."""


class ScheduleRun(Shape):
    """One occurrence of a schedule: the ticket it made, or why it made none."""

    at: str
    outcome: Literal["born", "launched", "skipped", "failed"]
    ticket: str
    """The ticket made, "" where none was."""
    title: str
    reason: str
    """Why no ticket was made, in the runner's words."""
    column: ColumnKey | Literal[""]
    """Where that ticket is now, "" where there is none or it left the board."""
    inferred: bool
    """Said from a ticket born before the runner kept its passes, rather than recorded."""


class ScheduleTotals(Shape):
    tickets: int
    cost: float
    average_cost: float | None
    """Over the tickets that have a cost; null when none has."""
    average_duration: float | None
    """In minutes, over the tickets that have a duration."""
    success: float | None
    """Done over done, failed and cancelled — from 0 to 1, null while none has finished."""


class ScheduleWeek(Shape):
    week: str
    """Its Monday."""
    tickets: int
    done: int
    open: int
    cost: float


class ScheduleActivity(Shape):
    """What one schedule made — `web/lineage.py`."""

    tickets: list[ScheduleTicket]
    """The newest first."""
    runs: list[ScheduleRun]
    """The newest first."""
    statuses: list[StatusCount]
    totals: ScheduleTotals
    weeks: list[ScheduleWeek]
    since: str
    """When the runner began keeping this schedule's passes; "" when it has kept none."""
    matched: int
    """How many tickets were attached by their title alone."""


# -- the conversation ----------------------------------------------------------


class Accepted(Shape):
    max_mb: float
    accepted: list[str]
    ffmpeg: bool


class Dictation(Shape):
    ready: bool
    why: str
    send: bool


class ChatState(Shape):
    id: str = omitted()
    """The console's own identifier of the open session, not Claude Code's."""
    title: str = omitted()
    model: str = omitted()
    """The model the session was given; empty: the default of the settings."""
    model_in_use: str = omitted()
    """What the next turn runs on: the session's own, else the default."""
    project: str = omitted()
    session_id: str
    turns: int
    resume_command: str
    stopping: bool = omitted()
    """Stop was pressed and the turn in flight has not ended yet."""
    attachments: Accepted = omitted()
    """What a message may carry: the extensions the server keeps, and how heavy."""
    dictation: Dictation = omitted()
    """Whether the microphone can be offered, and why not when it cannot."""
    queue: list[Queued] = omitted()
    """What was said while a turn ran, in order: sent one by one after it."""
    held: bool = omitted()
    """A turn ended before its time: the queue waits to be sent or thrown away."""


class Attached(Shape):
    """A file kept by the server for a message: what the transcript draws it from."""

    id: str
    name: str
    kind: Literal["image", "video", "document"]
    type: str
    size: int


class Queued(Shape):
    """A message sent while the workspace was answering: waiting for its turn."""

    id: str
    text: str
    at: str
    attachments: list[Attached] = omitted()


class Message(Shape):
    role: Literal["you", "workspace", "runner", "error", "command", "stopped"]
    """`stopped`: a turn of the workspace you ended, and what it had said by then.
    `runner`: what Ponos wrote on a ticket, in its discussion."""
    text: str
    at: str = omitted()
    attachments: list[Attached] = omitted()
    id: str = omitted()
    """The id the page gave a message it sent, or the one of a turn's answer."""
    parts: list[dict[str, Any]] = omitted()
    """What a turn of the workspace streamed, as TanStack AI's `UIMessage` parts."""
    seconds: float = omitted()
    cost: float = omitted()
    """In dollars, what the turn cost."""


class Chat(ChatState):
    """The conversation as the page opens it: what was said, and where it stands."""

    messages: list[Message]
    busy: bool = omitted()


class ChatSession(Shape):
    """One row of the Sessions page: a conversation the console has kept."""

    id: str
    title: str
    model: str
    project: str
    turns: int
    updated: str
    """The last message's date, ISO."""
    current: bool
    """The one the console is talking to now."""
    matched: Literal["title", "content"] = omitted()
    """With a search: found in the title, or deeper in the transcript."""


class ChatThread(Shape):
    """A conversation as `useChat` hydrates it (TanStack AI's `ChatHydrationResult`).

    The messages are TanStack AI's `UIMessage`s, typed by the package and not
    here; what Ponos adds rides in `metadata.ponos`.
    """

    messages: list[dict[str, Any]]
    activeRun: None  # noqa: N815 — TanStack AI's names
    """Never a run to rejoin: its events come on `/api/events`."""
    interrupts: None


class AguiEvent(Shape):
    """One AG-UI event of a turn of the workspace, for the page's `useChat`."""

    event: dict[str, Any]


class ChatSessions(Shape):
    sessions: list[ChatSession]


class Named(Shape):
    id: str
    name: str


class OpenRouterModel(Named):
    input: float | None
    """Dollars per million tokens read, None when OpenRouter does not say."""
    output: float | None
    tools: bool
    """Whether it can use tools: Claude Code needs them to work."""


class OpenRouterModels(Shape):
    configured: bool
    models: list[OpenRouterModel]
    error: str


class ChatModels(Shape):
    """What the model picker offers."""

    claude: list[Named]
    openrouter: OpenRouterModels
    recent: list[str]
    """Slugs and names the sessions last ran on, the latest first."""
    default: str
    in_use: str


class Talk(Shape):
    id: str
    mention: str
    messages: list[Message]
    waiting: bool
    """The last word on the page is a question a run asked, still unanswered."""


class Detached(Shape):
    removed: str
    """The file taken off the message, by its identifier."""


class Transcribed(Shape):
    """What a recording said, and the language it was heard in — empty: Whisper's guess."""

    text: str
    language: str


class CommandAccepted(Shape):
    """A command started: what runs, as the stream's `started` says it again."""

    argv: list[str]


# -- the runner ----------------------------------------------------------------


class Running(Shape):
    """A session in flight: the ticket it belongs to (its short id), and its log."""

    source: str
    log: str


class RunningCommit(Shape):
    """The commit the console runs: its full hash, its date, its subject."""

    commit: str
    date: str
    subject: str


class UpgradeProgress(Shape):
    """An update's progress, as the stream carries it."""

    phase: UpgradePhase
    detail: str
    """What it waits for while `waiting`; the version being installed while `installing`."""
    error: str
    target: str
    """The version being installed, or the one the console came back on."""
    log: list[str]
    log_path: str


class Upgrade(UpgradeProgress):
    """What the version at the top right knows: whether a newer one waits, and where to read about
    it."""

    available: bool
    current: str
    """The installed commit and the newest one, both short."""
    latest: str
    tag: str
    """The release the newest one is, on the release channel."""
    behind: int
    """How many commits behind the newest one, and their subjects, newest first."""
    commits: list[str]
    notes: str
    """The release notes, or the commits in between."""
    automatic: bool
    """Whether the console can install it itself; `manual` says why not."""
    manual: str
    command: str
    """What to type instead."""


class RunnerState(Shape):
    timer: str
    running: bool
    lock: str
    sessions: list[Running]
    """The sessions in flight, read from their logs by the server."""
    credits: float
    """When the credits come back, in seconds since the epoch — 0 while there are some."""
    credits_at: str
    """The same moment, as a clock reads it."""
    budget: float
    """`budget.daily_usd` once it is spent — 0 while there is room, or no limit."""
    budget_spent: float
    """What the sessions have cost since midnight."""
    workspace_root: str
    storage: str
    """`storage.mode`: "notion", "markdown", or "both"."""
    board_path: str
    """Where the Markdown board is, empty unless there is one."""
    interval_seconds: int
    model: str
    permission_mode: str
    claude: bool
    version: str
    """The release number and the commit it runs, `0.1.0+1a2b3c4` — or the number alone."""
    commit: RunningCommit = omitted()
    """The commit `version` names, for its tooltip — empty outside a git checkout."""
    update: str
    upgrade: Upgrade = omitted()
    """The update the version offers, and how far one is — see `web/upgrade.py`."""
    spend: float
    handled: int
    chat: ChatState
    commands: list[str]
    busy: bool


class Step(Shape):
    """A line of a session: the tool it used, and what it used it on — or, `said`, what the agent
    wrote."""

    label: str
    detail: str
    said: bool = omitted()
    position: int = omitted()
    """Where the step stands in its run, and when — only on a step read from the journal."""
    at: str = omitted()


class Run(Shape):
    """One run of a ticket, as the local journal keeps it — see `journal.py`."""

    id: int
    ticket: str
    title: str
    kind: str
    project: str
    agent: str
    session: str
    log: str
    started_at: str
    ended_at: str | None
    """Null while the run is going on — or when it was killed before it could say."""
    status: str | None
    """`done`, `blocked`, `failed`, `waiting` or `validated`."""
    reason: str
    cost_usd: float | None
    steps: int
    model: str = omitted()
    """What the run was asked to run on, and what its session said it ran on."""
    reported: str = omitted()
    model_label: str = omitted()
    """Whichever of the two is known, as `provider/model`."""


class Runs(Shape):
    runs: list[Run]


class RunSteps(Shape):
    """A page of a run's steps. `more`: there are older ones than the first here."""

    run: int
    count: int
    steps: list[Step]
    more: bool
    ended: bool


class LogEntry(Shape):
    """One session log on disk, as `/api/logs` lists it."""

    name: str
    ticket: str
    at: float
    size: int


class Logs(Shape):
    logs: list[LogEntry]


class LogSteps(Shape):
    """One session log, read as steps."""

    name: str
    count: int
    steps: list[Step]


class History(Shape):
    """The last lines of `ponos history`, newest first.

    Each is the entry a pass recorded — a run, a merge, a ticket a schedule made
    — and its keys are its kind's: `at`, `id` and `status` on every one.
    """

    entries: list[dict[str, Any]]


class ServiceLog(Shape):
    """The end of `ponos.log`, masked: what `ponos logs --service` prints."""

    path: str
    lines: list[str]


# -- the installation's health -------------------------------------------------


class HealthFix(Shape):
    """A fix Ponos can make itself — always asked for before it is made."""

    action: str
    label: str
    confirm: str
    missing: str
    target: str


class HealthNote(Shape):
    name: str
    said: list[str]


class HealthCheck(Shape):
    """One check of `health.py`: a sentence with `{{name}}` holes, and the params that fill them."""

    code: str
    group: Literal["notion", "github", "claude", "projects", "machine", "settings"]
    state: Literal["ok", "warn", "error", "info"]
    """`info` is a setting said rather than judged: `ponos doctor`'s grey line, left off the band."""
    title: str
    said: str
    params: dict[str, str]
    cause: str
    steps: list[str]
    url: str
    evidence: str
    """What a tool printed, quoted — never translated."""
    notes: list[HealthNote]
    """What each name in a list is worth: “Agent” and the sentences about it."""
    fix: HealthFix | None


class HealthReport(Shape):
    """What is wrong with the installation, checked now — the band over the dashboard."""

    checks: list[HealthCheck]
    problems: int
    checked_at: str


class HealthFixed(HealthReport):
    """The report again, once a fix was made."""

    done: str
    """What the fix did."""


# -- settings ------------------------------------------------------------------


class SettingField(Shape):
    name: str
    kind: Literal["text", "path", "int", "bool", "choice", "events", "lines", "secret"]
    label: str
    help: str
    choices: list[str]
    options: dict[str, str] = omitted()
    """A choice's value and the words it is shown in — the file keeps the value."""
    advanced: bool = omitted()
    """Folded under "advanced settings" until somebody asks for them."""
    fallback: Any
    after: str
    stated: bool
    value: str | float | bool | list[str] | None
    preview: str = omitted()
    variable: str = omitted()
    """A secret's variable, in secrets.env or the environment — never config.toml."""
    unit: str = omitted()
    """What a number counts — "seconds", "days" — drawn beside its box."""
    placeholder: str = omitted()
    """What an empty box says when there is no default to show."""
    environment: str = omitted()
    """The variable the runner reads this from instead of the file, when it is set."""
    grid: Literal["", "level", "type", "subtype"] = omitted()
    """A cell of the model table: the model of a `level`, where a `type` starts, or how a `subtype`
    moves it."""
    short: str = omitted()
    """The word heading its row or its column in that table."""
    unavailable: str = omitted()
    """Why it cannot be turned on on this machine — Docker missing — or empty when it can."""


class SettingSection(Shape):
    key: str
    title: str
    blurb: str
    pairs: str
    group: str
    """The page this card is on."""
    fold: str
    """The folded block it sits in, if any."""
    layout: str
    """`grid` for the model table; empty for a column of fields."""
    fields: list[SettingField]


class SettingGroup(Shape):
    """One of the six pages of the settings."""

    key: str
    title: str
    blurb: str


class SettingFold(Shape):
    """A folded block at the end of a page — the board's names, for one."""

    key: str
    title: str
    blurb: str


class Entry(Shape):
    name: str
    folder: bool


class Folder(Shape):
    """A folder of the runner's machine, for a path field to pick from."""

    folder: str
    parent: str
    """Empty at the root."""
    entries: list[Entry]
    more: int
    """How many more there were than the list holds."""


class Pair(Shape):
    """One row of a `name = value` table: a project and its path, an owner and its
    GitHub account. Which table it belongs to is the section's `pairs`."""

    name: str
    value: str


class Docker(Shape):
    """Whether Docker is installed on the runner's machine, and whether its daemon answers."""

    available: bool
    installed: bool


class OwnValidation(Shape):
    id: str
    name: str


class Settings(Shape):
    path: str
    usable: bool
    problem: str
    groups: list[SettingGroup]
    folds: list[SettingFold]
    sections: list[SettingSection]
    projects: list[Pair]
    github: list[Pair]
    docker: Docker = omitted()
    """Whether Docker answers here, which the local CI needs."""
    own_validation: list[OwnValidation] = omitted()
    """The projects that decide their automatic validation for themselves."""


class Saved(Shape):
    saved: list[str]
    after: list[str]


class Sizes(Shape):
    worktrees: int
    logs: int
    scratch: int


class Worktree(Shape):
    name: str
    size: int


class Disk(Shape):
    """The room the runner takes on this machine — see cleanup.py."""

    sizes: Sizes
    worktrees: list[Worktree]
    free_mb: float | None
    disk_mb: float | None
    min_free_disk_mb: float
    short: bool
    stale_worktree_days: int
    total: int
    measured_at: str
    tidied_at: str
    retention_days: int
    clean_done_worktrees: bool


class Cleaned(Disk):
    """What a tidy asked from the console removed, and the room left after it."""

    removed: int
    logs: int
    freed: int


class McpClient(Shape):
    id: str
    name: str
    scope: str


class McpOverview(Shape):
    """The addresses the console's MCP server is reached at, and who holds a key — never a key."""

    local: str
    public: str
    """Empty while `web.url` is not set."""
    clients: list[McpClient]


class McpServer(Shape):
    """One MCP server Claude Code holds, as `claude mcp list` says it."""

    name: str
    target: str
    state: Literal["ok", "auth", "error"]


class McpServers(Shape):
    available: bool
    failed: bool
    servers: list[McpServer]


class McpTest(Shape):
    """The answer of the connection test: `code` says why it failed, the page says what to do."""

    ok: bool
    code: str
    status: int
    seen: str = omitted()


# -- GitHub --------------------------------------------------------------------


class GithubInstallation(Shape):
    """One account a GitHub App is installed on, and what it reaches there."""

    id: int
    account: str
    selection: str
    """`all`, or `selected` when the repositories were picked one by one."""
    repositories: list[str]
    error: str


class GithubApp(Shape):
    """A GitHub App this console created — names and places, never a key."""

    slug: str
    name: str
    owner: str
    url: str
    settings_url: str
    install_url: str
    installations: list[GithubInstallation]
    error: str


class Missing(Shape):
    permission: str
    level: str


class GithubTokenCheck(Shape):
    """What a personal access token was found to be able to do — see `github_token.check`."""

    login: str
    kind: Literal["classic", "fine-grained"]
    repositories: list[str]
    writable: list[str]
    missing: list[Missing]
    warnings: list[str]
    ok: bool


class GithubToken(Shape):
    """The token as the console shows it: where it comes from, never the value."""

    configured: bool
    source: str
    mode: str
    vault: str
    create_url: str
    check: GithubTokenCheck = omitted()
    error: str = omitted()


class Github(Shape):
    """The GitHub Apps this console created, and the token beside them."""

    apps: list[GithubApp]
    token: GithubToken


class GithubManifest(Shape):
    """What the page posts to GitHub to create an app: where, and the manifest."""

    action: str
    manifest: str
    state: str


class GithubTokenSaved(GithubTokenCheck):
    """A pasted token, checked: kept only when a code ticket can work with it."""

    saved: bool


class GithubTokenForgotten(Shape):
    forgotten: bool
    tokens_url: str
    """Where GitHub revokes it: forgetting it here does not."""


class GithubDisconnected(Shape):
    forgotten: str
    """The app's slug."""
    settings_url: str
    """Where GitHub deletes it: forgetting it here does not."""


# -- statistics ----------------------------------------------------------------


class StatisticsDay(Shape):
    """One day of the statistics page. `open` is what was still open that evening, `cost` what was
    spent since the period began."""

    day: str
    created: int
    closed: int
    open: int
    cost: float


class Totals(Shape):
    open: int
    closed: int
    created: int
    cost: float


class StatusCount(Shape):
    key: ColumnKey
    count: int


class ProjectCount(Shape):
    name: str
    count: int


class Dated(Shape):
    history: int
    edited: int


class Week(Shape):
    week: str
    counts: dict[str, int]


class BlockCount(Block):
    count: int


class Blocks(Shape):
    total: int
    weeks: list[Week]
    causes: list[BlockCount]


class SubtypeCount(Subtype):
    count: int
    cost: float | None
    duration: float | None


class Subtypes(Shape):
    total: int
    weeks: list[Week]
    subtypes: list[SubtypeCount]


class MadeCell(Shape):
    """One count of tickets created: a type and a sub-type key, "" for none of them."""

    kind: str
    subtype: str
    project: str
    count: int


class MadeBucket(MadeCell):
    bucket: str


class Made(Shape):
    """The tickets created, as cells: by day or by week (named by its Monday), and for the period
    before."""

    unit: Literal["day", "week"]
    buckets: list[str]
    cells: list[MadeBucket]
    before: list[MadeCell]


class Statistics(Shape):
    """The statistics of one period — `web/statistics.py`."""

    start: str = Field(alias="from")
    to: str
    totals: Totals
    days: list[StatisticsDay]
    statuses: list[StatusCount]
    """The tickets created in the period, by the column they are in now."""
    projects: list[ProjectCount]
    """The same tickets, by project; "" for a ticket with none."""
    dated: Dated
    """How many closings the runner's history dated, and how many Notion's last edit had to."""
    average: float | None
    """What a ticket closed in the period cost in all; null when none was."""
    blocks: Blocks = omitted()
    """The stops of the period: by week (named by its Monday), and by cause, the commonest first."""
    subtypes: Subtypes = omitted()
    """The code tickets closed in the period: by week and by sub-type, with what one of each
    took."""
    made: Made = omitted()
    """The tickets created in the period, by bucket, type, sub-type and project — see
    `lib/made.ts`."""


# -- goals ---------------------------------------------------------------------


class GoalTicket(Shape):
    id: str
    short: str
    title: str
    column: str
    """The key of the board's column it stands in, as `Goal.tickets` counts it."""


class Goal(Shape):
    """One row of the goals database, and how far its tickets have gone."""

    id: str
    name: str
    url: str
    description: str
    """The row's own columns, as written in Notion — empty where it has none."""
    criterion: str
    due: str
    status: str
    priority: str
    projects: list[str]
    """The names of the projects it is for."""
    project_ids: list[str] = omitted()
    """Those projects' page ids, as the form sends them back."""
    tickets: dict[str, int]
    """How many of the tickets pointing at it are in each column, by the column's key — counted
    from the board, not read off a rollup. A column with none is not a key."""
    linked: list[GoalTicket] = omitted()
    """The tickets pointing at it, as the form lists them and its page draws them."""


class Goals(Shape):
    goals: list[Goal]
    configured: bool
    """Whether the workspace has a goals database at all."""


class GoalNamed(Shape):
    id: str
    name: str


class GoalSaved(Shape):
    id: str


class TicketGoal(Shape):
    id: str
    goal_id: str
    """Empty when the ticket now serves none."""


# -- ideas ---------------------------------------------------------------------


class IdeaAuthor(Shape):
    """Who wrote an idea, or last changed it: Ponos, or a person by the name and picture they had
    then."""

    kind: Literal["ponos", "human"]
    name: str
    """Empty when the console could not tell who it was talking to."""
    avatar: str


class Edited(Shape):
    name: str
    avatar: str
    at: str


class Idea(Shape):
    """One idea, Ponos's or written by hand, as `/api/ideas` says it."""

    id: int
    scope: Literal["global", "project"]
    project: str
    """The project it was proposed for; empty for the workspace's."""
    kind: Literal["ticket", "project"]
    category: Literal["", "ux", "feature", "security", "technical"]
    """What the idea is about — exactly one of them, or "" for one nobody sorted."""
    score: int | None
    """Relevance out of 100; null for an idea not scored (yet)."""
    score_reason: str
    """The line that says why it has that score."""
    score_error: str
    """Why the last attempt to score it gave nothing; empty when none failed."""
    scoring: bool
    """Whether the light model is scoring it now: the pill says "…"."""
    title: str
    description: str
    where: str
    done: list[str]
    out: list[str]
    status: IdeaStatus
    ticket: str
    """The draft it became once kept."""
    created: str
    """The project it created when it was the idea of one."""
    decided_at: str | None
    created_at: str
    changed_at: str
    """When its status last changed, whichever way."""
    origin: Literal["ponos", "manual"]
    author: IdeaAuthor
    edited: Edited | None
    """The last person who reworded it; null when nobody has."""


class StatusCounts(Shape):
    proposed: int
    kept: int
    discarded: int
    ticket: int


class IdeaList(Shape):
    """Every idea of one scope, and how many are in each status."""

    scope: Literal["global", "project", "all"]
    project: str
    ideas: list[Idea]
    counts: StatusCounts


class Ideas(Shape):
    """The ideas of one scope: the pile, the last decisions, and whether one can be taken back."""

    scope: Literal["global", "project"]
    project: str
    ideas: list[Idea]
    decided: list[Idea]
    undo: Idea | None


class Unscored(Shape):
    """The ideas with no score, and what scoring them may cost at most."""

    count: int
    calls: int
    """One call a scope and twenty ideas, each of them capped."""
    ceiling_usd: float
    model: str
    running: bool
    """Whether a pass is scoring them now."""


class Found(Shape):
    """What asking for a batch brought back."""

    ideas: list[Idea]
    error: str


class Undone(Shape):
    """The last decision taken back: the idea proposed again, and what it had been."""

    idea: Idea
    was: IdeaStatus


class IdeasSettings(Shape):
    """The keys of `[runner]` that say how ideas are found on their own, as the dialog has them."""

    schedule: str
    at: str
    day: str
    every_hours: int
    cron: str
    scope: str
    workspace: bool
    per_batch: int
    skip_above: int
    budget_usd: float
    notify: bool
    model: str


class IdeasProject(Shape):
    """A project in the dialog's list, and whether a pass covers it."""

    id: str
    name: str
    enabled: bool
    own: bool | None
    """The project's own word, None when the file speaks for it."""


class IdeasSkipped(Shape):
    name: str
    reason: str


class IdeasLastPass(Shape):
    at: str
    found: int
    cost_usd: float
    projects: int
    skipped: list[IdeasSkipped]
    error: str


class IdeasPlan(Shape):
    """When ideas are found on their own, for which projects, and how the last pass went."""

    settings: IdeasSettings
    projects: list[IdeasProject]
    problem: str
    """Why the schedule cannot fire; empty when it can, or is off."""
    next: str
    last: IdeasLastPass | None
    running: bool
    timezone: str
    saved: list[str] = omitted()
    """The keys a save wrote, in the answer to one."""


# -- decisions -----------------------------------------------------------------


class Solution(Shape):
    """One thing a card waiting on you offers — see `decisions.py`."""

    key: str
    column: ColumnKey
    """The column the ticket goes to."""
    needs: Literal["", "text", "note", "model", "titles"]
    """What it needs before it can be done: nothing, words, a note, a model, titles."""
    text: str
    """The option's own words, or an instruction ready to edit."""
    number: int
    """The option it is, from 1, for the session's options and points to check."""
    label: str
    """The choice in the runner's words, as the ticket will be told it."""


class Question(Shape):
    ask: str
    mode: Literal["yes-no", "choice", "free"]
    options: list[str]


class Checks(Shape):
    state: Literal["passed", "failed", "pending", "none", "unknown"]
    link: str
    listed: list[Check]


class Decision(Shape):
    """Why a blocked ticket waits, or what a ticket in review brought back.

    `category` to `model` are a blocked ticket's; `summary` to `caveats`, a
    reviewed one's.
    """

    id: str
    column: Literal["blocked", "review"]
    solutions: list[Solution]
    category: str = omitted()
    declared: bool = omitted()
    """Whether the session named the category, rather than its words giving it away."""
    reported: bool = omitted()
    """Whether a run said anything at all: a ticket set aside by hand did not."""
    reason: str = omitted()
    done: str = omitted()
    detail: str = omitted()
    question: Question | None = omitted()
    model: str = omitted()
    summary: str = omitted()
    facts: str = omitted()
    pull_request: str = omitted()
    checks: Checks = omitted()
    caveats: list[str] = omitted()


class Decided(Moved):
    """What a decision did: the move, and what was said or made on the way."""

    column: ColumnKey
    told: list[str]
    """The lines written on the ticket, after the one that says who relayed them."""
    created: list[str]
    """The tickets it made, by their page ids."""


# -- the bell ------------------------------------------------------------------


class Notification(Shape):
    id: int
    kind: Literal["question", "review", "ci", "failed", "blocked"]
    ticket: str
    title: str
    at: str
    read: bool


class Bell(Shape):
    """The bell as the stream says it — a state, replayed to every tab that connects."""

    items: list[Notification]
    unread: int


# -- signing in, and the first connection --------------------------------------


class Ok(Shape):
    ok: bool


class SetupState(Shape):
    """What the first connection's page needs before it draws a step."""

    claimed: bool
    """Somebody already said how this console is opened: the account step is done."""
    signed_in: bool
    code: bool
    """The first connection comes from outside this machine and has to give the code."""
    code_drawn: bool
    """The console drew a code when it started — without one, outside is refused."""
    container: bool
    version: str
    storage: str


SetupHealth = Literal["ok", "missing", "error"]


class Provisioned(Shape):
    """What a step that builds something did, line by line, and what it could not."""

    steps: list[tuple[str, str]]
    """Each a kind — `created`, `kept` — and the sentence that says it."""
    problem: str


class Claimed(Provisioned):
    """The first connection made: the browser that made it is signed in as `email`."""

    email: str


class Checked(Shape):
    """A check of the first connection: does it work, and who, or why not."""

    ok: bool
    said: str


class ProviderChecked(Checked):
    command: str = omitted()
    """For the CLI only: what to run in a terminal to sign it in."""


class ClaudeLogin(Checked):
    command: str
    """What to run in a terminal to sign it in."""


class SetupProvider(Shape):
    state: SetupHealth
    provider: Literal["cli", "api_key", "openrouter"]
    """The provider in use: the one the file names, else the one it behaved as."""
    stated: str
    """The one the file names, empty for none."""
    account: str
    key: str
    """The key, masked: its first and last letters."""
    route_sessions: bool
    said: str


class SetupModel(Shape):
    state: SetupHealth
    model: str
    auto: bool
    said: str


class SetupBoard(Shape):
    state: SetupHealth
    storage: str
    workspace: str
    path: str
    tickets: int | None
    """Null when the board could not be counted."""
    said: str


class SetupGithub(Shape):
    """Which GitHub account a pull request would be opened as — or why none."""

    state: SetupHealth
    account: str
    via: Literal["token", "app", "GH_TOKEN", "gh"]
    said: str
    command: str
    create_url: str
    """Where GitHub makes a personal access token."""


class SetupProjects(Shape):
    state: SetupHealth
    root: str
    repositories: int
    configured: int


class SetupChannels(Shape):
    state: SetupHealth
    active: list[str]


class SetupEnvironment(Shape):
    state: SetupHealth
    container: bool
    version: str


class Need(Shape):
    """One thing the machine needs, and the command that installs it when it is missing."""

    name: str
    ok: bool
    required: bool
    said: str
    fix: str


class SetupMachine(Shape):
    """git, Claude Code and its sign-in, the disk — what `doctor` checks under Tools."""

    state: SetupHealth
    needs: list[Need]


class SetupSummary(Shape):
    """What the installation amounts to: one entry per thing that has to work."""

    machine: SetupMachine
    provider: SetupProvider
    model: SetupModel
    board: SetupBoard
    github: SetupGithub
    projects: SetupProjects
    channels: SetupChannels
    environment: SetupEnvironment


class NotionProvisioned(Provisioned):
    board: SetupBoard


class SharedPage(Shape):
    id: str
    title: str
    url: str


class SharedBoard(Shape):
    id: str
    url: str


class Shared(Shape):
    """What Notion has shared with the integration so far."""

    ok: bool
    said: str
    refused: bool = omitted()
    """Notion said the token is not one of its own: the page says it, translated."""
    name: str
    """The integration's name, as Notion shows it in the Connections menu."""
    pages: list[SharedPage]
    boards: list[SharedBoard]


class Repository(Shape):
    name: str
    path: str
    remote: str


class ProjectChoices(Shape):
    """The repositories this machine already has, and the projects already on the board."""

    root: str
    said: str
    repositories: list[Repository]
    projects: list[Named]


class Demo(Shape):
    """Where the demonstration ticket stands, and — once its run ended badly — why."""

    id: str
    title: str
    url: str
    column: ColumnKey
    status: str
    progress: str
    running: bool
    code: int | None
    """The run's exit code, null while it runs or when it was not started here."""
    said: str


class Doctor(Shape):
    """`ponos doctor`, as the terminal prints it."""

    code: int
    text: str


class ChannelCheck(Shape):
    name: str
    ok: bool
    said: str


class ChannelsProvisioned(Provisioned):
    channels: list[ChannelCheck]


# -- what the stream carries ---------------------------------------------------


class SessionsEvent(Shape):
    """The sessions running now — a state, replayed to every tab that connects."""

    sessions: list[Running]


class StepEvent(Step):
    source: str
    log: str


class ChatReset(Shape):
    stage: Literal["reset"]


class ChatOpened(Shape):
    stage: Literal["opened"]


class ChatRenamed(Shape):
    stage: Literal["renamed"]
    id: str = omitted()


class ChatDeleted(Shape):
    stage: Literal["deleted"]
    id: str = omitted()


class ChatModel(Shape):
    stage: Literal["model"]
    model: str = omitted()


class ChatSent(Shape):
    stage: Literal["sent"]
    text: str
    attachments: list[Attached] = omitted()
    session_id: str


class ChatQueue(Shape):
    stage: Literal["queue"]
    queue: list[Queued]
    held: bool


class ChatStep(Step):
    stage: Literal["step"]


class ChatStopping(Shape):
    stage: Literal["stopping"]


class ChatStopped(Shape):
    stage: Literal["stopped"]
    text: str
    seconds: float = omitted()
    session_id: str = omitted()


class ChatAnswer(Shape):
    stage: Literal["answer", "failed"]
    text: str
    ok: bool = omitted()
    cost_usd: float = omitted()
    seconds: float = omitted()
    session_id: str = omitted()


class CommandStarted(Shape):
    stage: Literal["started"]
    argv: list[str]


class CommandLine(Shape):
    stage: Literal["line"]
    text: str


class CommandEnded(Shape):
    stage: Literal["ended"]
    code: int


class TalkEvent(Message):
    ticket: str


class SyncEvent(Shape):
    """When the board last agreed with Notion, and what does not. `board.describe`."""

    synced_at: str
    reconciled_at: str
    drift: int
    """Tickets the last full read found the incremental reads had wrong."""
    pending: int
    failed: int
    conflicts: int
    error: str
    """Why the last read failed, empty when it did not."""


class NoticeEvent(Shape):
    where: str
    message: str


class Stream(Shape):
    """What `/api/events` sends: each event's data, under the event's name."""

    board: Board
    """Whole: on connecting, and when the columns changed."""
    changes: BoardChanges
    sessions: SessionsEvent
    notifications: Bell
    step: StepEvent
    chat: (
        ChatReset
        | ChatOpened
        | ChatRenamed
        | ChatDeleted
        | ChatModel
        | ChatSent
        | ChatQueue
        | ChatStep
        | ChatStopping
        | ChatStopped
        | ChatAnswer
    )
    agui: AguiEvent
    command: CommandStarted | CommandLine | CommandEnded
    talk: TalkEvent
    sync: SyncEvent
    upgrade: UpgradeProgress
    notice: NoticeEvent
