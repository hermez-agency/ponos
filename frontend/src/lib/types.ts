/* The shapes the Python side sends, written down once.
 *
 * Every one of these mirrors a dict built in `src/ponos/web/` — `api.py`
 * for the reads and writes, `console.py` and `live.py` for what comes down the
 * event stream. When a field is added there, it is added here, and TypeScript
 * says which components have to care.
 */

import type { UpgradePhase } from "./upgrade"
import type { WorkTime } from "./worktime"

export type ColumnKey =
  | "draft"
  | "ready"
  | "running"
  | "blocked"
  | "review"
  | "validated"
  | "failed"
  | "done"
  | "cancelled"

export interface Ticket {
  id: string
  short: string
  title: string
  url: string
  status: string
  column: ColumnKey
  project: string
  /** The project's page id, empty for a ticket without one. */
  project_id?: string
  /** The project's icon, as `Project.icon` is: emoji, image or empty. */
  project_icon?: Picture
  /** The project's kind of work, `code` or `document`. */
  kind: string
  /** The ticket's own type, as the board spells it: Code, Writing, External action… */
  type: string
  /** A score from 0 to 100, an empty cell read as 50; null on a board without the column. */
  priority: number | null
  model: string
  /** `model` as `provider/model` — claude/haiku, deepseek/r1 — said by `models.label`. */
  model_label?: string
  progress: string
  runner: string
  pull_request: string
  session: string
  session_link: string
  cost: number | null
  duration: number | null
  scheduled: string
  created: string
  /** Notion's `last_edited_time`: when a done ticket closed, where the runner's history does not say. */
  edited: string
  /** A move that has not reached Notion: on its way, refused, or not made
   * because Notion had been changed meanwhile — see `web/board.py`. */
  sync?: "pending" | "failed" | "conflict"
  /** Why, when it is not on its way. */
  sync_error?: string
  /** The status the move was to. */
  sync_status?: string
  /** On a ready card only: why it is still there — see `held` in `web/board.py`. */
  held?: { reason: string; detail: string }
  /** On a blocked or failed card only: why it stopped — see `blocks.py`. */
  block?: Block | null
  /** In review with a pull request that has checks only: where they stand — see `ci.py`. */
  ci?: Ci | null
  /** A code ticket's sub-type, by its key — `bug`, `docs` — or empty: see `subtypes.py`. */
  subtype?: string
  /** How long Ponos worked on it, the clock stopped while it waited — null when no run was made: see `worktime.py`. */
  worktime?: WorkTime | null
}

/** One sub-type of a code ticket, whole, as the board sends the table of them. */
export interface Subtype {
  key: string
  /** How the board writes it: « Amélioration », « Sécurité ». */
  option: string
  /** The developers' word — « Feature », « Security » — shown as it is in
   * every language: a sub-type is never translated, see `SUBTYPES` in subtypes.py. */
  label: string
  /** The prefix of its commits: `fix`, `feat`… */
  commit: string
  /** Its CHANGELOG section, empty for none. */
  changelog: string
}

export type CiState = "pending" | "passed" | "failed"

/** A pull request's checks as the runner last read them: stored, never fetched with the board. */
export interface Ci {
  state: CiState
  /** The board's word for it (« en cours », « réussi », « erreur »). */
  label: string
  /** `gh pr checks` buckets: pass, fail, pending, skipping, cancel. */
  checks: { name: string; bucket: string; link: string }[]
  /** GitHub's page listing the checks. */
  link: string
}

/** The families a cause belongs to, each drawn with its icon. */
export type BlockFamily = "merge" | "session" | "infrastructure" | "question" | "access"

/** What a stopped card offers: run it again, answer, clean, the base's CI, the pull request. */
export type BlockAction = "retry" | "answer" | "clean" | "base-ci" | "open-pr"

/** Why a ticket stopped, as `blocks.py` describes it — its words in both languages. */
export interface Block {
  code: string
  family: BlockFamily
  /** Who has to move: Ponos, you, or something outside both. */
  who: "ponos" | "user" | "external"
  action: BlockAction
  /** What the runner may do on its own: `retry:n`, `wait-base` or `ask`. */
  policy: string
  label: { en: string; fr: string }
  help: { en: string; fr: string }
}

/** A ticket, with the page under it: the brief, the report, the notes between. */
export interface TicketDetail extends Ticket {
  /** The page's blocks, flattened the way the runner reads them. */
  content: string
  /** The model it runs on: the last session's own word, then the column, then the defaults. */
  model_in_use?: { label: string; full: string; default: boolean }
  /** The prompt run at every change of the ticket's status, empty for none. */
  on?: string
}

/** One change of status met on a ticket that carries an « On » prompt, and what running it did. */
export interface Transition {
  id: number
  old: string
  new: string
  /** How many generations of tickets created by an execution it is below a person's. */
  depth: number
  state: "pending" | "running" | "ok" | "failed" | "skipped" | string
  seen_at: string
  started_at: string
  ended_at: string
  cost_usd: number | null
  seconds: number | null
  session: string
  /** What the session said, or why it did not run. */
  result: string
}

export interface Board {
  tickets: Ticket[]
  /** Whether this board has a `validated` column the runner would honour. */
  validate?: boolean
  /** Whether this board has a `cancelled` column to give a ticket up in. */
  cancel?: boolean
  columns: { key: ColumnKey; name: string }[]
  /** What a new ticket may be given beside its title, for the columns this
   * board has: a column it lacks is not a key here. */
  choices?: Partial<Record<"type" | "model" | "subtype", { value: string; label: string }[]>>
  /** Whether this board has a priority column to write a score in. */
  priority?: boolean
  /** The sub-types of a code ticket, in the order they are offered. */
  subtypes?: Subtype[]
  /** What a ticket with no model of its own runs on: `runner.model`, empty for Claude Code's own. */
  model?: string
  /** Which board the stream sent, for the changes that follow it. */
  version?: number
}

/** What moved on the board since version `base`, as the stream sends it. */
export interface BoardChanges {
  base: number
  version: number
  /** Changed or new, each with the ticket it now follows (`""`: the first). */
  changed: { after: string; ticket: Ticket }[]
  removed: string[]
}

export interface Project {
  /** Empty for a project the configuration names and the board has never heard of. */
  id: string
  name: string
  kind: string
  url: string
  /** What the project page declares, when it declares anything. */
  repository?: string
  path?: string
  /** What it does, in a sentence, and its public address — the page's columns, empty when it has none. */
  description?: string
  site?: string
  /** The `[projects]` entry of the configuration, where there is one. */
  configured?: string
  /** Where the clone really is on this machine — said only by the project's own page, empty when there is none. */
  located?: string
  /** Where this row came from: the board, or the file on this machine. */
  source?: "board" | "config"
  /** The banner of its page, and the mark in front of its name. See `Picture`. */
  cover?: Picture
  icon?: Picture
}

/** What a repository and a folder turn out to be, asked while a new project is written. */
export interface ProjectCheck {
  /** The repository as it will be kept: `https://github.com/owner/name`. */
  repository?: string
  /** Where this machine already has its clone; empty, it is cloned at the first ticket. */
  cloned?: string
  repository_error?: string
  path?: string
  /** The folder's `origin` remote — a GitHub address when it is GitHub's. */
  origin?: string
  path_error?: string
}

/* One of a project's two pictures, as the console draws it.
 *
 * `src` is the console's own address for the image, never the board's: a file
 * Notion keeps is behind a URL that is dead within the hour, so the server
 * keeps a copy and serves that. */
export interface Picture {
  kind: "image" | "emoji" | ""
  src?: string
  emoji?: string
  /** The address a pasted picture lives at — somebody else's, so not a secret. */
  url?: string
  /** Chosen here, and not yet taken by the board. */
  pending?: boolean
  /** Why the board did not take it — it is tried again at the next reading. */
  error?: string
  /** Changed on both sides between two readings: which side's picture won. */
  conflict?: "notion" | "console" | ""
}

/** What a picture's change answers: both pictures of the project, as they now are. */
export interface Pictures {
  id: string
  cover: Picture
  icon: Picture
}

/** One project, opened: the row, and what is written on its page. */
export interface ProjectDetail extends Project {
  content: string
  version: string
}

/** A project's brief as the editor opens it, and what saving it would not keep. */
export interface ProjectBrief {
  content: string
  /** What `saveProject` is handed back as `base`: refused if the page no longer says it. */
  version: string
  /** The kinds of Notion content Markdown cannot hold, and how many of each. */
  losses: Record<string, number>
}

/** The four types of ticket, as the runner keys them. */
export type TicketKind = "code" | "publication" | "writing" | "external"

/** One switch of the automatic validation, worded as the global card words it. */
export interface ValidationField {
  kind: TicketKind
  /** The global setting's key, `runner.force_validated_code`. */
  name: string
  label: string
  help: string
}

/** What a project decides for itself — see project_settings.py. */
export interface ProjectSettings {
  id: string
  validation: {
    /** Whether the project has its own switches; false, the file's apply. */
    own: boolean
    /** What applies to its tickets: its own switches, or the file's. */
    values: Record<TicketKind, boolean>
    /** The file's, whatever the project says. */
    global: Record<TicketKind, boolean>
    fields: ValidationField[]
  }
}

/** What deleting a project did, as the server counts it. */
export interface ProjectDeleted {
  id: string
  name: string
  /** Where the page can be restored from; empty on a board of files. */
  url: string
  tickets: number
  blocked: number
  trashed: number
}

export interface Projects {
  projects: Project[]
  workspace_root: string
  /** `storage.mode`: which board these came off. */
  storage: string
}

/** The standing context: what reaches every ticket before the ticket itself. */
export interface Context {
  text: string
  /** The page it is written on, "" where the workspace has none. */
  page: string
  /** What that page is called, for the sentence that says it is missing. */
  where: string
  storage: string
  editable: boolean
}

/** One row of the Schedules database: a recipe for a ticket, and how often it is born. */
export interface Schedule {
  id: string
  name: string
  url: string
  /** "Hourly" | "Daily" | "Weekly" | "Monthly", or empty where nobody picked one. */
  cadence: string
  at: string
  day: string
  active: boolean
  /** When the next ticket is due, and when the last one was made. Empty for "never yet". */
  next: string
  last: string
  /** The ticket the last occurrence made, addressed as the board addresses one. */
  ticket: string
  /** The project's name, when the server already knew it; the page it points at, always. */
  project: string
  project_id: string
  model: string
  /** A score from 0 to 100, null when the schedule says none: its tickets are born at 50. */
  priority: number | null
  /** What its tickets are born as, by their keys — `code`, `bug` — empty to let them be guessed. */
  type?: string
  subtype?: string
  /** What stops this schedule being acted on, in the words `doctor` prints. */
  problem: string
}

/** One schedule opened: the row, and its page body — the brief of every ticket it makes. */
export interface ScheduleDetail extends Schedule {
  body: string
}

export interface Schedules {
  /** `runner.schedule`: off, and nothing is born however the rows are ticked. */
  enabled: boolean
  /** Whether the workspace has a Schedules database at all. */
  database: boolean
  /** The zone the hours are said in (the runner's), for the calendar to lay them out in; empty when unknown. */
  timezone?: string
  /** What that page is called, for the sentence that says it is missing. */
  page: string
  /** `storage.mode`: which board these came off. */
  storage?: string
  schedules: Schedule[]
  /** What the form offers for the type and the sub-type: only the columns the database has. */
  choices?: Partial<Record<"type" | "subtype", { value: string; label: string }[]>>
}

export interface ChatState {
  /** The console's own identifier of the open session, not Claude Code's. */
  id?: string
  title?: string
  /** The model the session was given; empty: the default of the settings. */
  model?: string
  /** What the next turn runs on: the session's own, else the default. */
  model_in_use?: string
  project?: string
  session_id: string
  turns: number
  resume_command: string
  /** Stop was pressed and the turn in flight has not ended yet. */
  stopping?: boolean
  /** What a message may carry: the extensions the server keeps, and how heavy. */
  attachments?: { max_mb: number; accepted: string[]; ffmpeg: boolean }
  /** Whether the microphone can be offered, and why not when it cannot. */
  dictation?: { ready: boolean; why: string; send: boolean }
}

/** One row of the Sessions page: a conversation the console has kept. */
export interface ChatSession {
  id: string
  title: string
  model: string
  project: string
  turns: number
  /** The last message's date, ISO. */
  updated: string
  /** The one the console is talking to now. */
  current: boolean
  /** With a search: found in the title, or deeper in the transcript. */
  matched?: "title" | "content"
}

/** What the model picker offers. */
export interface ChatModels {
  claude: { id: string; name: string }[]
  openrouter: { configured: boolean; models: { id: string; name: string }[]; error: string }
  /** Slugs and names the sessions last ran on, the latest first. */
  recent: string[]
  default: string
  in_use: string
}

/** A file kept by the server for a message: what the transcript draws it from. */
export interface Attached {
  id: string
  name: string
  kind: "image" | "video" | "document"
  type: string
  size: number
}

export interface RunnerState {
  timer: string
  running: boolean
  lock: string
  /** The sessions in flight, read from their logs by the server. */
  sessions: Running[]
  /** When the credits come back, in seconds since the epoch — 0 while there are some. */
  credits: number
  /** The same moment, as a clock reads it. */
  credits_at: string
  /** `budget.daily_usd` once it is spent — 0 while there is room, or no limit. */
  budget: number
  /** What the sessions have cost since midnight. */
  budget_spent: number
  workspace_root: string
  /** `storage.mode`: "notion", "markdown", or "both". */
  storage: string
  /** Where the Markdown board is, empty unless there is one. */
  board_path: string
  interval_seconds: number
  model: string
  permission_mode: string
  claude: boolean
  /** The release number and the commit it runs, `0.1.0+1a2b3c4` — or the number alone. */
  version: string
  /** The commit `version` names, for its tooltip — empty outside a git checkout. */
  commit?: RunningCommit
  update: string
  /** The update the version offers, and how far one is — see `web/upgrade.py`. */
  upgrade?: Upgrade
  spend: number
  handled: number
  chat: ChatState
  commands: string[]
  busy: boolean
}

/** The commit the console runs: its full hash, its date, its subject. */
export interface RunningCommit {
  commit: string
  date: string
  subject: string
}

/** An update's progress, as the stream carries it. */
export interface UpgradeProgress {
  phase: UpgradePhase
  /** What it waits for while `waiting`; the version being installed while `installing`. */
  detail: string
  error: string
  /** The version being installed, or the one the console came back on. */
  target: string
  log: string[]
  log_path: string
}

/** What the version at the top right knows: whether a newer one waits, and where to read about it. */
export interface Upgrade extends UpgradeProgress {
  available: boolean
  /** The installed commit and the newest one, both short. */
  current: string
  latest: string
  /** The release the newest one is, on the release channel. */
  tag: string
  /** How many commits behind the newest one, and their subjects, newest first. */
  behind: number
  commits: string[]
  /** The release notes, or the commits in between. */
  notes: string
  /** Whether the console can install it itself; `manual` says why not. */
  automatic: boolean
  manual: string
  /** What to type instead. */
  command: string
}

/** A line of a session: the tool it used, and what it used it on — or, `said`, what the agent wrote. */
export interface Step {
  label: string
  detail: string
  said?: boolean
  /** Where the step stands in its run, and when — only on a step read from the journal. */
  position?: number
  at?: string
}

/** One run of a ticket, as the local journal keeps it — see `journal.py`. */
export interface Run {
  id: number
  ticket: string
  title: string
  kind: string
  project: string
  agent: string
  session: string
  log: string
  started_at: string
  /** Null while the run is going on — or when it was killed before it could say. */
  ended_at: string | null
  status: "done" | "blocked" | "failed" | "waiting" | "validated" | null | string
  reason: string
  cost_usd: number | null
  steps: number
  /** What the run was asked to run on, and what its session said it ran on. */
  model?: string
  reported?: string
  /** Whichever of the two is known, as `provider/model`. */
  model_label?: string
}

/** A page of a run's steps. `more`: there are older ones than the first here. */
export interface RunSteps {
  run: number
  count: number
  steps: Step[]
  more: boolean
  ended: boolean
}

/** `stopped`: a turn of the workspace you ended, and what it had said by then.
 * `runner`: what Ponos wrote on a ticket, in its discussion. */
export type Role = "you" | "workspace" | "runner" | "error" | "command" | "stopped"

export interface Message {
  role: Role
  text: string
  at?: string
  attachments?: Attached[]
}

export interface Talk {
  id: string
  mention: string
  messages: Message[]
  /** The last word on the page is a question a run asked, still unanswered. */
  waiting: boolean
}

/** A session in flight: the ticket it belongs to (its short id), and its log. */
export interface Running {
  source: string
  log: string
}

/** One session log on disk, as `/api/logs` lists it. */
export interface LogEntry {
  name: string
  ticket: string
  at: number
  size: number
}

/* -- what the stream carries ------------------------------------------------ */

/** The sessions running now — a state, replayed to every tab that connects. */
export interface SessionsEvent {
  sessions: Running[]
}

export interface StepEvent extends Step {
  source: string
  log: string
}

export type ChatEvent =
  | { stage: "reset" }
  | { stage: "opened" }
  | { stage: "renamed"; id?: string }
  | { stage: "deleted"; id?: string }
  | { stage: "model"; model?: string }
  | { stage: "sent"; text: string; attachments?: Attached[]; session_id: string }
  | ({ stage: "step" } & Step)
  | { stage: "stopping" }
  | { stage: "stopped"; text: string; seconds?: number; session_id?: string }
  | {
      stage: "answer" | "failed"
      text: string
      ok?: boolean
      cost_usd?: number
      seconds?: number
      session_id?: string
    }

export type CommandEvent =
  | { stage: "started"; argv: string[] }
  | { stage: "line"; text: string }
  | { stage: "ended"; code: number }

export interface TalkEvent extends Message {
  ticket: string
}

/** When the board last agreed with Notion, and what does not. `board.describe`. */
export interface SyncEvent {
  synced_at: string
  reconciled_at: string
  /** Tickets the last full read found the incremental reads had wrong. */
  drift: number
  pending: number
  failed: number
  conflicts: number
  /** Why the last read failed, empty when it did not. */
  error: string
}

export interface NoticeEvent {
  where: string
  message: string
}

/* -- settings --------------------------------------------------------------- */

export type FieldKind = "text" | "path" | "int" | "bool" | "choice" | "events" | "lines" | "secret"

export interface SettingField {
  name: string
  kind: FieldKind
  label: string
  help: string
  choices: string[]
  /** A choice's value and the words it is shown in — the file keeps the value. */
  options?: Record<string, string>
  /** Folded under "advanced settings" until somebody asks for them. */
  advanced?: boolean
  fallback: unknown
  after: string
  stated: boolean
  value: string | number | boolean | string[] | null
  preview?: string
  /** A secret's variable, in secrets.env or the environment — never config.toml. */
  variable?: string
  /** What a number counts — "seconds", "days" — drawn beside its box. */
  unit?: string
  /** What an empty box says when there is no default to show. */
  placeholder?: string
  /** The variable the runner reads this from instead of the file, when it is set. */
  environment?: string
  /** A cell of the model table: the model of a `level`, where a `type` starts, or how a `subtype` moves it. */
  grid?: "" | "level" | "type" | "subtype"
  /** The word heading its row or its column in that table. */
  short?: string
}

export interface SettingSection {
  key: string
  title: string
  blurb: string
  pairs: string
  /** The page this card is on. */
  group: string
  /** The folded block it sits in, if any. */
  fold: string
  /** `grid` for the model table; empty for a column of fields. */
  layout: string
  fields: SettingField[]
}

/** One of the six pages of the settings. */
export interface SettingGroup {
  key: string
  title: string
  blurb: string
}

/** A folded block at the end of a page — the board's names, for one. */
export interface SettingFold {
  key: string
  title: string
  blurb: string
}

/** A folder of the runner's machine, for a path field to pick from. */
export interface Folder {
  folder: string
  /** Empty at the root. */
  parent: string
  entries: { name: string; folder: boolean }[]
  /** How many more there were than the list holds. */
  more: number
}

/** One row of a `name = value` table: a project and its path, an owner and its
 * GitHub account. Which table it belongs to is the section's `pairs`. */
export interface Pair {
  name: string
  value: string
}

export interface Settings {
  path: string
  usable: boolean
  problem: string
  groups: SettingGroup[]
  folds: SettingFold[]
  sections: SettingSection[]
  projects: Pair[]
  github: Pair[]
  /** The projects that decide their automatic validation for themselves. */
  own_validation?: { id: string; name: string }[]
}

/** The room the runner takes on this machine — see cleanup.py. */
export interface Disk {
  sizes: { worktrees: number; logs: number; scratch: number }
  worktrees: { name: string; size: number }[]
  free_mb: number | null
  disk_mb: number | null
  min_free_disk_mb: number
  short: boolean
  stale_worktree_days: number
  total: number
  measured_at: string
  tidied_at: string
  retention_days: number
  clean_done_worktrees: boolean
}

/** What a tidy asked from the console removed, and the room left after it. */
export interface Cleaned extends Disk {
  removed: number
  logs: number
  freed: number
}

/** The addresses the console's MCP server is reached at, and who holds a key — never a key. */
export interface McpOverview {
  local: string
  /** Empty while `web.url` is not set. */
  public: string
  clients: { id: string; name: string; scope: string }[]
}

/** One account a GitHub App is installed on, and what it reaches there. */
export interface GithubInstallation {
  id: number
  account: string
  /** `all`, or `selected` when the repositories were picked one by one. */
  selection: string
  repositories: string[]
  error: string
}

/** A GitHub App this console created — names and places, never a key. */
export interface GithubApp {
  slug: string
  name: string
  owner: string
  url: string
  settings_url: string
  install_url: string
  installations: GithubInstallation[]
  error: string
}

/** What the page posts to GitHub to create an app: where, and the manifest. */
export interface GithubManifest {
  action: string
  manifest: string
  state: string
}

/** One MCP server Claude Code holds, as `claude mcp list` says it. */
export interface McpServer {
  name: string
  target: string
  state: "ok" | "auth" | "error"
}

export interface McpServers {
  available: boolean
  failed: boolean
  servers: McpServer[]
}

/** The answer of the connection test: `code` says why it failed, the page says what to do. */
export interface McpTest {
  ok: boolean
  code: string
  status: number
  seen?: string
}

export interface Saved {
  saved: string[]
  after: string[]
}

/** What a settings field may become on the way back to the file. */
export type SettingValue = string | number | boolean | string[] | null

/** One day of the statistics page. `open` is what was still open that evening, `cost` what was spent since the period began. */
export interface StatisticsDay {
  day: string
  created: number
  closed: number
  open: number
  cost: number
}

/** The statistics of one period — `web/statistics.py`. */
export interface Statistics {
  from: string
  to: string
  totals: { open: number; closed: number; created: number; cost: number }
  days: StatisticsDay[]
  /** The tickets created in the period, by the column they are in now. */
  statuses: { key: ColumnKey; count: number }[]
  /** The same tickets, by project; "" for a ticket with none. */
  projects: { name: string; count: number }[]
  /** How many closings the runner's history dated, and how many Notion's last edit had to. */
  dated: { history: number; edited: number }
  /** What a ticket closed in the period cost in all; null when none was. */
  average: number | null
  /** The stops of the period: by week (named by its Monday), and by cause, the commonest first. */
  blocks?: {
    total: number
    weeks: { week: string; counts: Record<string, number> }[]
    causes: (Block & { count: number })[]
  }
  /** The code tickets closed in the period: by week and by sub-type, with what one of each took. */
  subtypes?: {
    total: number
    weeks: { week: string; counts: Record<string, number> }[]
    subtypes: (Subtype & { count: number; cost: number | null; duration: number | null })[]
  }
  /** The tickets created in the period, by bucket, type, sub-type and project — see `lib/made.ts`. */
  made?: Made
}

/** One count of tickets created: a type and a sub-type key, "" for none of them. */
export interface MadeCell {
  kind: string
  subtype: string
  project: string
  count: number
}

/** The tickets created, as cells: by day or by week (named by its Monday), and for the period before. */
export interface Made {
  unit: "day" | "week"
  buckets: string[]
  cells: (MadeCell & { bucket: string })[]
  before: MadeCell[]
}

/* -- ideas ---------------------------------------------------------------- */

export type IdeaStatus = "proposed" | "kept" | "discarded" | "ticket"

/** What an idea is about — exactly one of them, or "" for one nobody sorted. */
export type IdeaCategory = "" | "ux" | "feature" | "security" | "technical"

/** Who wrote an idea, or last changed it: Ponos, or a person by the name and picture they had then. */
export interface IdeaAuthor {
  kind: "ponos" | "human"
  /** Empty when the console could not tell who it was talking to. */
  name: string
  avatar: string
}

/** One idea, Ponos's or written by hand, as `/api/ideas` says it. */
export interface Idea {
  id: number
  scope: "global" | "project"
  /** The project it was proposed for; empty for the workspace's. */
  project: string
  kind: "ticket" | "project"
  category: IdeaCategory
  /** Relevance out of 100; null for an idea not scored (yet). */
  score: number | null
  /** The line that says why it has that score. */
  score_reason: string
  /** Why the last attempt to score it gave nothing; empty when none failed. */
  score_error: string
  /** Whether the light model is scoring it now: the pill says "…". */
  scoring: boolean
  title: string
  description: string
  where: string
  done: string[]
  out: string[]
  status: IdeaStatus
  /** The draft it became once kept. */
  ticket: string
  /** The project it created when it was the idea of one. */
  created: string
  decided_at: string | null
  created_at: string
  /** When its status last changed, whichever way. */
  changed_at: string
  origin: "ponos" | "manual"
  author: IdeaAuthor
  /** The last person who reworded it; null when nobody has. */
  edited: { name: string; avatar: string; at: string } | null
}

/** Every idea of one scope, and how many are in each status. */
export interface IdeaList {
  scope: "global" | "project" | "all"
  project: string
  ideas: Idea[]
  counts: Record<IdeaStatus, number>
}

/** The ideas of one scope: the pile, the last decisions, and whether one can be taken back. */
export interface Ideas {
  scope: "global" | "project"
  project: string
  ideas: Idea[]
  decided: Idea[]
  undo: Idea | null
}

/** The ideas with no score, and what scoring them may cost at most. */
export interface Unscored {
  count: number
  /** One call a scope and twenty ideas, each of them capped. */
  calls: number
  ceiling_usd: number
  model: string
  /** Whether a pass is scoring them now. */
  running: boolean
}

/** What asking for a batch brought back. */
export interface Found {
  ideas: Idea[]
  error: string
}

/** One thing a card waiting on you offers — see `decisions.py`. */
export interface Solution {
  key: string
  /** The column the ticket goes to. */
  column: ColumnKey
  /** What it needs before it can be done: nothing, words, a note, a model, titles. */
  needs: "" | "text" | "note" | "model" | "titles"
  /** The option's own words, or an instruction ready to edit. */
  text: string
  /** The option it is, from 1, for the session's options and points to check. */
  number: number
  /** The choice in the runner's words, as the ticket will be told it. */
  label: string
}

/** Why a blocked ticket waits, or what a ticket in review brought back. */
export interface Decision {
  id: string
  column: "blocked" | "review"
  solutions: Solution[]
  /* -- blocked -- */
  category?: string
  /** Whether the session named the category, rather than its words giving it away. */
  declared?: boolean
  /** Whether a run said anything at all: a ticket set aside by hand did not. */
  reported?: boolean
  reason?: string
  done?: string
  detail?: string
  question?: { ask: string; mode: "yes-no" | "choice" | "free"; options: string[] } | null
  model?: string
  /* -- review -- */
  summary?: string
  facts?: string
  pull_request?: string
  checks?: {
    state: "passed" | "failed" | "pending" | "none" | "unknown"
    link: string
    listed: { name: string; bucket: string; link: string }[]
  }
  caveats?: string[]
}

/* -- the bell ---------------------------------------------------------------- */

export type NotificationKind = "question" | "review" | "ci" | "failed" | "blocked"

export interface Notification {
  id: number
  kind: NotificationKind
  ticket: string
  title: string
  at: string
  read: boolean
}

/** The bell as the stream says it — a state, replayed to every tab that connects. */
export interface Bell {
  items: Notification[]
  unread: number
}
