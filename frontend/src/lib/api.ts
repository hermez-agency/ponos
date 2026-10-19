import type {
  Attached,
  Bell,
  Board,
  ColumnKey,
  Decision,
  Cleaned,
  McpOverview,
  McpServers,
  McpTest,
  Disk,
  Folder,
  GithubApp,
  GithubManifest,
  Found,
  Idea,
  Unscored,
  IdeaList,
  Ideas,
  LogEntry,
  ChatModels,
  ChatSession,
  ChatState,
  Context,
  Message,
  Pair,
  Pictures,
  Project,
  ProjectBrief,
  ProjectCheck,
  ProjectDeleted,
  ProjectDetail,
  Projects,
  ProjectSettings,
  Run,
  Transition,
  RunnerState,
  RunSteps,
  UpgradeProgress,
  Saved,
  ScheduleDetail,
  Schedules,
  Settings,
  Statistics,
  SettingValue,
  Step,
  Talk,
  TicketDetail,
} from "./types"
import type { HealthReport } from "./health"
import type { SetupState, Summary } from "./setup"

/* Talking to the server.
 *
 * Two things every request here carries, and neither is decoration:
 *
 * - `X-Ponos: 1`. The server refuses a write without it, because a page
 *   you have open in another tab can post a form to this port with your cookie
 *   attached but cannot set a header of its own without a preflight this server
 *   never answers. The header is the difference between "the console asked" and
 *   "some page you had open asked".
 * - `credentials: "same-origin"`, which is what sends that cookie at all.
 */

const GUARD = { "X-Ponos": "1" }

export class ApiError extends Error {
  readonly status: number
  /* The payload as it arrived, under the name react-resource-view looks for.
   *
   * A form drawn by that package hands whatever a write threw to its own
   * `normalizeApiError`, which reads an error's `data` and passes it to the
   * dialect. Without it the sentence the server refused with reaches the
   * browser's console and nowhere else — and a save that fails quietly is a
   * save you think worked. */
  readonly data: { error: string; violations?: { propertyPath: string; message: string }[] }

  /* `violations`, when the server says which field it refused: the form then
   * draws the sentence under that field, not only in a toast. */
  constructor(message: string, status: number, violations?: { propertyPath: string; message: string }[]) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.data = violations?.length ? { error: message, violations } : { error: message }
  }
}

let leaving = false

/* The sign-in page is what the server answers `/` with to a browser it does
 * not know, so going back to it is reloading the page. Once: two requests
 * refused in the same second must not reload twice. */
function backToTheDoor() {
  if (leaving) return
  leaving = true
  window.location.reload()
}

/** Whether the server still knows this browser — asked when the stream closes. */
export async function signedOut(): Promise<boolean> {
  try {
    const response = await fetch("/api/state", {
      headers: { ...GUARD },
      credentials: "same-origin",
    })
    if (response.status !== 401) return false
  } catch {
    // The server is down, not the session: the stream is tried again.
    return false
  }
  backToTheDoor()
  return true
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const options: RequestInit = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json", ...GUARD },
        body: JSON.stringify(body),
      }
    : { headers: { ...GUARD } }
  return answer<T>(await fetch(path, { ...options, credentials: "same-origin" }))
}

/* A picture is sent as the file it is rather than as JSON: base64 would make
 * it a third heavier, and the server reads it straight into the upload. */
async function upload<T>(path: string, file: Blob, name: string): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": file.type, "X-Filename": encodeURIComponent(name), ...GUARD },
    body: file,
    credentials: "same-origin",
  })
  return answer<T>(response)
}

async function answer<T>(response: Response): Promise<T> {
  // Signed out underneath the page — a password changed, a cookie expired, the
  // console restarted with another token. Every call after this one would fail
  // the same way, each with its own toast: the page goes back to the door.
  if (response.status === 401) backToTheDoor()
  const payload = await response.json().catch(() => ({}) as Record<string, unknown>)
  if (!response.ok) {
    const said = payload as { error?: string; violations?: ApiError["data"]["violations"] }
    throw new ApiError(said.error || String(response.status), response.status, said.violations)
  }
  return payload as T
}

/* A body that is not JSON — a file, a recording — sent as it is, under its own
 * type. One file a request: the server streams it to disk rather than parsing
 * a multipart form the standard library no longer reads. */
async function send<T>(path: string, body: Blob): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": body.type || "application/octet-stream", ...GUARD },
    body,
    credentials: "same-origin",
  })
  if (response.status === 401) backToTheDoor()
  const payload = await response.json().catch(() => ({}) as Record<string, unknown>)
  if (!response.ok) {
    const said = (payload as { error?: string }).error
    throw new ApiError(said || String(response.status), response.status)
  }
  return payload as T
}

/** Where a file of the conversation is served back from, for its thumbnail. */
export const attachmentUrl = (id: string) => `/api/chat/attachments/${id}`

export const api = {
  state: () => request<RunnerState>("/api/state"),
  board: () => request<Board>("/api/board"),
  projects: () => request<Projects>("/api/projects"),
  context: () => request<Context>("/api/context"),
  schedules: () => request<Schedules>("/api/schedules"),
  schedule: (id: string) => request<ScheduleDetail>(`/api/schedules/${id}`),
  chat: () => request<{ messages: Message[] } & ChatState & { busy?: boolean }>("/api/chat"),
  settings: () => request<Settings>("/api/settings"),
  folder: (path: string) => request<Folder>(`/api/settings/folder?path=${encodeURIComponent(path)}`),
  statistics: (from: string, to: string, project?: string) =>
    request<Statistics>(
      `/api/statistics?from=${from}&to=${to}` +
        (project === undefined ? "" : `&project=${encodeURIComponent(project)}`)
    ),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  createProject: (values: Record<string, unknown>) => request<Project>("/api/projects", values),
  checkProject: (repository: string, path: string) =>
    request<ProjectCheck>(
      `/api/projects/check?repository=${encodeURIComponent(repository)}&path=${encodeURIComponent(path)}`
    ),
  projectBrief: (id: string) => request<ProjectBrief>(`/api/projects/${id}/brief`),
  projectSettings: (id: string) => request<ProjectSettings>(`/api/projects/${id}/settings`),
  ticket: (id: string) => request<TicketDetail>(`/api/tickets/${id}`),
  talk: (id: string) => request<Talk>(`/api/tickets/${id}/talk`),
  logs: (ticket = "") =>
    request<{ logs: LogEntry[] }>(ticket ? `/api/logs?ticket=${encodeURIComponent(ticket)}` : "/api/logs"),
  log: (name: string) =>
    request<{ name: string; count: number; steps: Step[] }>(`/api/logs/${encodeURIComponent(name)}`),
  runs: (id: string) => request<{ runs: Run[] }>(`/api/tickets/${id}/runs`),
  /** The executions of a ticket's « On » prompt, newest first. */
  transitions: (id: string) =>
    request<{ transitions: Transition[] }>(`/api/tickets/${id}/transitions`),
  /** Write the prompt run at every change of the ticket's status; empty removes it. */
  setOn: (id: string, on: string) => request<{ id: string; on: string }>(`/api/tickets/${id}/on`, { on }),
  /** A run's last steps; `before`, those older than a position; `after`, those newer. */
  runSteps: (run: number, page: { before?: number; after?: number } = {}) =>
    request<RunSteps>(
      `/api/runs/${run}/steps` +
        (page.after ? `?after=${page.after}` : page.before ? `?before=${page.before}` : "")
    ),

  createTicket: (ticket: {
    title: string
    body: string
    project: string
    ready: boolean
    /** Each left out, or empty, for a ticket that does not say: an empty type
     * is the runner's to deduce, an empty priority is 50. `type` is one of the
     * four keys, not a label; `priority` a score from 0 to 100. */
    priority?: number | ""
    type?: string
    model?: string
    /** A sub-type's key — `bug`, `docs` — and only on a code ticket. */
    subtype?: string
  }) => request<{ id: string; title: string }>("/api/tickets", ticket),
  /** `from` is the status the card showed: Notion saying anything else by the
   * time the write goes out is somebody else's move, not overwritten. */
  setStatus: (id: string, column: string, from?: string) =>
    request<{ id: string; status: string; sync?: string }>(`/api/tickets/${id}/status`, {
      column,
      from,
    }),
  tell: (id: string, text: string) =>
    request<unknown>(`/api/tickets/${id}/talk`, { text }),
  /** What a blocked card, or one in review, offers to do about it. */
  decision: (id: string) => request<Decision>(`/api/tickets/${id}/decision`),
  decide: (
    id: string,
    choice: { key: string; number?: number; text?: string; model?: string; titles?: string[] }
  ) =>
    request<{ id: string; status: string; column: ColumnKey; told: string[]; created: string[] }>(
      `/api/tickets/${id}/decision`,
      choice
    ),
  command: (line: string) => request<unknown>("/api/command", { line }),
  send: (text: string, attachments: string[] = []) =>
    request<unknown>("/api/chat", { text, attachments }),
  attach: (file: File, name: string) =>
    send<Attached>(`/api/chat/attachments?name=${encodeURIComponent(name)}`, file),
  detach: (id: string) => request<unknown>(`/api/chat/attachments/${id}/remove`, {}),
  transcribe: (audio: Blob, language: string) =>
    send<{ text: string; language: string }>(
      `/api/chat/transcribe?lang=${encodeURIComponent(language)}`,
      audio
    ),
  resetChat: () => request<unknown>("/api/chat/reset", {}),
  sessions: (query = "") =>
    request<{ sessions: ChatSession[] }>(`/api/chat/sessions?q=${encodeURIComponent(query)}`),
  openSession: (id: string) => request<ChatState>(`/api/chat/sessions/${id}/open`, {}),
  renameSession: (id: string, title: string) =>
    request<ChatState>(`/api/chat/sessions/${id}/rename`, { title }),
  deleteSession: (id: string) => request<ChatState>(`/api/chat/sessions/${id}/delete`, {}),
  chatModels: () => request<ChatModels>("/api/chat/models"),
  setChatModel: (model: string) => request<ChatState>("/api/chat/model", { model }),
  linkSession: (id: string, project: string) =>
    request<ChatState>(`/api/chat/sessions/${id}/project`, { project }),
  stopChat: () => request<unknown>("/api/chat/stop", {}),
  saveSettings: (payload: {
    settings: Record<string, SettingValue>
    projects?: Pair[]
    github?: Pair[]
  }) => request<Saved>("/api/settings", payload),
  saveContext: (text: string) => request<{ text: string }>("/api/context", { text }),
  saveProject: (id: string, values: Record<string, unknown>) =>
    request<ProjectDetail>(`/api/projects/${id}`, values),
  saveProjectSettings: (
    id: string,
    values: { validation: { own: boolean; values?: Partial<ProjectSettings["validation"]["values"]> } }
  ) => request<ProjectSettings>(`/api/projects/${id}/settings`, values),
  deleteProject: (id: string, values: { confirm: string; trash_tickets: boolean }) =>
    request<ProjectDeleted>(`/api/projects/${id}/delete`, values),
  setPicture: (
    id: string,
    slot: "cover" | "icon",
    value: { url: string } | { emoji: string } | { remove: true }
  ) => request<Pictures>(`/api/projects/${id}/image/${slot}`, value),
  uploadPicture: (id: string, slot: "cover" | "icon", file: Blob, name: string) =>
    upload<Pictures>(`/api/projects/${id}/image/${slot}`, file, name),
  saveSchedule: (id: string, values: Record<string, unknown>) =>
    request<{ id: string }>(`/api/schedules/${id}`, values),
  launchSchedule: (id: string) =>
    request<{ ticket: string; title: string }>(`/api/schedules/${id}/launch`, {}),
  createSchedule: (values: Record<string, unknown>) =>
    request<{ id: string; name: string }>("/api/schedules", values),
  ideas: (project = "") =>
    request<Ideas>(`/api/ideas${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  /** An empty `project` is the workspace's ideas. */
  findIdeas: (project = "") => request<Found>("/api/ideas/generate", { project }),
  /** Every idea of one scope, thrown away and turned into tickets included. */
  allIdeas: (project = "", everywhere = false) =>
    request<IdeaList>(
      `/api/ideas/all${everywhere ? "?scope=all" : project ? `?project=${encodeURIComponent(project)}` : ""}`
    ),
  /** An idea written by hand; an empty `project` is the workspace's. */
  writeIdea: (values: {
    title: string
    description: string
    project: string
    kind?: Idea["kind"]
    category?: Idea["category"]
  }) => request<Idea>("/api/ideas", values),
  editIdea: (id: number, values: { title: string; description: string; category?: Idea["category"] }) =>
    request<Idea>(`/api/ideas/${id}`, values),
  /** Kept for later: nothing is written on the board. */
  keepIdea: (id: number) => request<Idea>(`/api/ideas/${id}/keep`, {}),
  discardIdea: (id: number) => request<Idea>(`/api/ideas/${id}/discard`, {}),
  /** A draft ticket — or, for the idea of a project, the project and its first ticket. */
  ticketIdea: (id: number) => request<Idea>(`/api/ideas/${id}/ticket`, {}),
  reopenIdea: (id: number) => request<Idea>(`/api/ideas/${id}/reopen`, {}),
  /** How many ideas have no score, and what scoring them may cost at most — said before it starts.
   * `project` null is every scope's, "" the workspace's. */
  unscoredIdeas: (project: string | null = null) =>
    request<Unscored>(
      `/api/ideas/unscored${project === null ? "?scope=all" : project ? `?project=${encodeURIComponent(project)}` : ""}`
    ),
  /** Scores them, behind the answer: the list is told as each batch is done. */
  scoreIdeas: (project: string | null = null) =>
    request<Unscored>("/api/ideas/score", project === null ? {} : { project }),
  /** Takes back the last decision of one scope. */
  undoIdea: (project = "") => request<{ idea: Idea; was: string }>("/api/ideas/undo", { project }),
  refresh: () => request<unknown>("/api/refresh", {}),
  /** One notification read, or all of them; the bell it leaves is the answer. */
  readNotifications: (id?: number) =>
    request<Bell>("/api/notifications/read", id === undefined ? {} : { id }),
  /** What is wrong with the installation, checked now. */
  health: () => request<HealthReport>("/api/health"),
  /** One fix a check offered — the page has asked first, and says so. */
  fixHealth: (action: string, target: string) =>
    request<HealthReport>("/api/health/fix", { action, target, confirmed: true }),
  disk: () => request<Disk>("/api/disk"),
  clean: () => request<Cleaned>("/api/disk/clean", {}),
  mcp: () => request<McpOverview>("/api/mcp"),
  githubApps: () => request<{ apps: GithubApp[] }>("/api/github"),
  connectGithub: (organisation: string) =>
    request<GithubManifest>("/api/github/connect", { organisation }),
  disconnectGithub: (slug: string) =>
    request<{ forgotten: string; settings_url: string }>("/api/github/disconnect", { slug }),
  /* Slow, and so its own call: Claude Code starts every server to see if it answers. */
  mcpServers: () => request<McpServers>("/api/mcp/servers"),
  testMcp: (target: "local" | "public") => request<McpTest>("/api/mcp/test", { target }),
  /* Nothing in the body: which version, and how it is installed, is the
   * server's to know. */
  upgrade: () => request<UpgradeProgress>("/api/update", {}),
  cancelUpgrade: () => request<UpgradeProgress>("/api/update/cancel", {}),

  /* The first connection. Its own state is asked without the door's reload:
   * a console nobody has claimed answers it to anybody, and a 401 there is an
   * answer to draw — the sign-in — not a page to leave. */
  setupState: async (): Promise<SetupState | null> => {
    const response = await fetch("/api/setup", { headers: { ...GUARD }, credentials: "same-origin" })
    return response.ok ? ((await response.json()) as SetupState) : null
  },
  claim: (typed: { code: string; email: string; password: string; confirm: string }) =>
    request<{ steps: [string, string][]; problem: string; email: string }>("/api/setup", typed),
  summary: () => request<Summary>("/api/setup/summary"),
  claudeLogin: () => request<Checked & { command: string }>("/api/setup/claude"),
  saveProvider: (chosen: { provider: string; key?: string; route_sessions?: boolean }) =>
    request<Checked & { command?: string }>("/api/setup/provider", chosen),
  saveNotion: (typed: { token: string; page: string }) =>
    request<Provisioned & { board: Summary["board"] }>("/api/setup/notion", typed),
  github: () => request<Summary["github"]>("/api/setup/github"),
  saveChannels: (typed: Record<string, string>) =>
    request<Provisioned & { channels: { name: string; ok: boolean; said: string }[] }>(
      "/api/setup/channels",
      typed
    ),
}

/** A check of the first connection: does it work, and who, or why not. */
export interface Checked {
  ok: boolean
  said: string
}

/** What a step that builds something did, line by line, and what it could not. */
export interface Provisioned {
  steps: [string, string][]
  problem: string
}

/** The message of whatever went wrong, however it went wrong. */
export function why(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
