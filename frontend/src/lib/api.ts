import createClient from "openapi-fetch"

import type { components, paths } from "./api-types"
import { t } from "./i18n"
import { SILENT, refusalOf } from "./refusals"
import type { Role } from "./role"
import type { Idea, IdeasSettings, Pair, ProjectSettings, SettingValue, VaultChange, VaultNew } from "./types"

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
 *
 * The rest is openapi-fetch reading `api-types.d.ts`: a path, its method, its
 * parameters, its body and what it answers are one entry of the schema, so a
 * call to a route that does not exist, or a shape the route does not answer,
 * fails to compile rather than at the first click.
 */

const client = createClient<paths>({ headers: { "X-Ponos": "1" }, credentials: "same-origin" })

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
    // The form draws `data.error` as it stands: it is given in the page's language.
    const error = told(message)
    this.data = violations?.length ? { error, violations } : { error }
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
    if ((await client.GET("/api/state")).response.status !== 401) return false
  } catch {
    // The server is down, not the session: the stream is tried again.
    return false
  }
  backToTheDoor()
  return true
}

type Violations = ApiError["data"]["violations"]

/* The refusal of a server that said no sentence — kept in English like the
 * rest, and translated where it is shown. */
const silent = (status: number) => SILENT.replace("{{status}}", String(status))

/* What a call answered, whichever route it was: openapi-fetch gives the
 * route's own shape as `data` when the answer is a success, and leaves it out
 * otherwise. */
type Answered<T> = { data?: T; error?: unknown; response: Response }

async function answer<T>(pending: Promise<Answered<T>>): Promise<T> {
  const { data, error, response } = await pending
  // Signed out underneath the page — a password changed, a cookie expired, the
  // console restarted with another token. Every call after this one would fail
  // the same way, each with its own toast: the page goes back to the door.
  if (response.status === 401) backToTheDoor()
  if (!response.ok || data === undefined) {
    const said = refusal(error)
    throw new ApiError(said.error || silent(response.status), response.status, said.violations)
  }
  return data
}

/* The sentence a refusal carries. The schema describes what each route answers
 * when it works, not the `{"error": …}` every one of them answers when it does
 * not: it is read here, field by field, from whatever came back. */
function refusal(payload: unknown): { error: string; violations?: Violations } {
  if (typeof payload !== "object" || payload === null) return { error: "" }
  const error = "error" in payload && typeof payload.error === "string" ? payload.error : ""
  if (!("violations" in payload) || !Array.isArray(payload.violations)) return { error }
  return { error, violations: payload.violations }
}

/* A body that is not JSON — a picture, a file, a recording — sent as it is,
 * under its own type: base64 would make a picture a third heavier, and the
 * server streams the bytes to disk rather than parsing a multipart form the
 * standard library no longer reads. One file a request.
 *
 * The schema has no body for these routes — the server reads the raw stream,
 * not a model, and the picture's route reads JSON from it too when what comes
 * is not an image — so openapi-fetch builds the request without one, and the
 * body is put in it on the way out, under the type the call already set. */
const carrying = (body: Blob | string) => (request: Request) => fetch(new Request(request, { body }))

/** Where a file of the conversation is served back from, for its thumbnail. */
export const attachmentUrl = (id: string) => `/api/chat/attachments/${id}`

/** Where a file of the library is served from: inline for a preview, or as a download. */
export const libraryUrl = (id: number, download = false) =>
  `/api/library/${id}/file${download ? "?download=1" : ""}`

/* A body's fields with a default on the server are required in the schema's
 * types — openapi-typescript reads a default as a value always there — so a
 * call that may leave one out sends it as that default, the one the server
 * would have used: `createTicket` and `decide` below. */
export const api = {
  state: () => answer(client.GET("/api/state")),
  board: () => answer(client.GET("/api/board")),
  projects: () => answer(client.GET("/api/projects")),
  goals: () => answer(client.GET("/api/goals")),
  context: () => answer(client.GET("/api/context")),
  createGoal: (values: Record<string, unknown>) => answer(client.POST("/api/goals", { body: values })),
  saveGoal: (id: string, values: Record<string, unknown>) =>
    answer(client.POST("/api/goals/{goal_id}", { params: { path: { goal_id: id } }, body: values })),
  deleteGoal: (id: string) =>
    answer(client.POST("/api/goals/{goal_id}/delete", { params: { path: { goal_id: id } } })),
  setTicketGoal: (ticket: string, goal: string) =>
    answer(client.POST("/api/tickets/{ticket_id}/goal", { params: { path: { ticket_id: ticket } }, body: { goal } })),
  /** « Run now »: a free place, or `full` — and with `force`, a place past the limit, once. */
  launch: (ticket: string, force = false) =>
    answer(
      client.POST("/api/tickets/{ticket_id}/launch", { params: { path: { ticket_id: ticket } }, body: { force } })
    ),
  /** The ticket's document: its part « What was done », written by hand. */
  setDocument: (ticket: string, content: string) =>
    answer(
      client.POST("/api/tickets/{ticket_id}/document", {
        params: { path: { ticket_id: ticket } },
        body: { content },
      })
    ),
  /** A score from 0 to 100; empty is the middle one, 50. */
  setPriority: (ticket: string, priority: number | "") =>
    answer(
      client.POST("/api/tickets/{ticket_id}/priority", {
        params: { path: { ticket_id: ticket } },
        body: { priority },
      })
    ),
  schedules: () => answer(client.GET("/api/schedules")),
  schedule: (id: string) =>
    answer(client.GET("/api/schedules/{schedule_id}", { params: { path: { schedule_id: id } } })),
  scheduleActivity: (id: string) =>
    answer(client.GET("/api/schedules/{schedule_id}/activity", { params: { path: { schedule_id: id } } })),
  /** The conversation spoken in last: where a browser that follows none starts. */
  latestChat: () => answer(client.GET("/api/chat")),
  chat: (id: string) => answer(client.GET("/api/chat/{identifier}", { params: { path: { identifier: id } } })),
  chatThread: (threadId: string) =>
    answer(client.GET("/api/chat/{identifier}/agui", { params: { path: { identifier: threadId } } })),
  runChat: (id: string, input: components["schemas"]["RunAgentInput"]) =>
    answer(client.POST("/api/chat/{identifier}/agui", { params: { path: { identifier: id } }, body: input })),
  settings: () => answer(client.GET("/api/settings")),
  folder: (path: string) => answer(client.GET("/api/settings/folder", { params: { query: { path } } })),
  statistics: (from: string, to: string, project?: string) =>
    answer(client.GET("/api/statistics", { params: { query: { from, to, project } } })),
  project: (id: string) =>
    answer(client.GET("/api/projects/{project_id}", { params: { path: { project_id: id } } })),
  createProject: (values: Record<string, unknown>) => answer(client.POST("/api/projects", { body: values })),
  checkProject: (repository: string, path: string) =>
    answer(client.GET("/api/projects/check", { params: { query: { repository, path } } })),
  projectBrief: (id: string) =>
    answer(client.GET("/api/projects/{project_id}/brief", { params: { path: { project_id: id } } })),
  projectSettings: (id: string) =>
    answer(client.GET("/api/projects/{project_id}/settings", { params: { path: { project_id: id } } })),
  projectNotes: (id: string) =>
    answer(client.GET("/api/projects/{project_id}/notes", { params: { path: { project_id: id } } })),
  /** One `action` on the notes: keep (a proposal, maybe `edited`), drop, add, edit or delete. */
  saveProjectNotes: (
    id: string,
    values: { action: "keep" | "drop" | "add" | "edit" | "delete"; text?: string; index?: number; edited?: string }
  ) =>
    answer(client.POST("/api/projects/{project_id}/notes", { params: { path: { project_id: id } }, body: values })),
  /** What a ticket being written is likely to cost and take; null without enough history. */
  estimate: (query: { project: string; type: string; subtype: string; model: string }) =>
    answer(client.GET("/api/estimate", { params: { query } })),
  ticket: (id: string) =>
    answer(client.GET("/api/tickets/{ticket_id}", { params: { path: { ticket_id: id } } })),
  talk: (id: string) =>
    answer(client.GET("/api/tickets/{ticket_id}/talk", { params: { path: { ticket_id: id } } })),
  logs: (ticket = "") =>
    answer(client.GET("/api/logs", { params: { query: { ticket: ticket || undefined } } })),
  log: (name: string) => answer(client.GET("/api/logs/{name}", { params: { path: { name } } })),
  runs: (id: string) =>
    answer(client.GET("/api/tickets/{ticket_id}/runs", { params: { path: { ticket_id: id } } })),
  /** The executions of a ticket's « On » prompt, newest first. */
  transitions: (id: string) =>
    answer(client.GET("/api/tickets/{ticket_id}/transitions", { params: { path: { ticket_id: id } } })),
  /** What was done to a ticket from the console, by whom, newest first. */
  audit: (id: string) => answer(client.GET("/api/tickets/{ticket_id}/audit", { params: { path: { ticket_id: id } } })),
  /** The accounts of the console, and the invitations not yet taken: an admin's. */
  accounts: () => answer(client.GET("/api/accounts")),
  /** A link for one more account, given once: it is kept only as its digest. */
  invite: (role: Role) => answer(client.POST("/api/invitations", { body: { role } })),
  withdrawInvitation: (id: number) =>
    answer(client.POST("/api/invitations/{number}/delete", { params: { path: { number: id } } })),
  setRole: (id: number, role: Role) =>
    answer(client.POST("/api/accounts/{number}/role", { params: { path: { number: id } }, body: { role } })),
  /** The account gone, and every browser signed into it with it. */
  deleteAccount: (id: number) =>
    answer(client.POST("/api/accounts/{number}/delete", { params: { path: { number: id } } })),
  /** What Ponos remembers — memory.py. `scope` is "", "global" or a project's id. */
  memories: (query: { scope?: string; kind?: string; status?: string; search?: string } = {}) =>
    answer(client.GET("/api/memories", { params: { query } })),
  addMemory: (values: Record<string, unknown>) => answer(client.POST("/api/memories", { body: values })),
  changeMemory: (id: number, values: Record<string, unknown>) =>
    answer(client.PUT("/api/memories/{identifier}", { params: { path: { identifier: id } }, body: values })),
  decideMemory: (id: number, action: "accept" | "refuse") =>
    answer(
      client.POST("/api/memories/{identifier}/{action}", { params: { path: { identifier: id, action } } })
    ),
  deleteMemory: (id: number) =>
    answer(client.DELETE("/api/memories/{identifier}", { params: { path: { identifier: id } } })),
  importMemories: () => answer(client.POST("/api/memories/import")),
  memoryAutoAccept: (on: boolean) =>
    answer(client.POST("/api/memories/options", { body: { auto_accept: on } })),
  /** The library of reference files — library.py. `project` keeps what that project's sessions are told. */
  library: (query: { project?: string; tag?: string; search?: string } = {}) =>
    answer(client.GET("/api/library", { params: { query } })),
  uploadToLibrary: (
    file: File,
    details: { description?: string; tags?: string; projects?: string } = {}
  ) =>
    answer(
      client.POST("/api/library/upload", {
        params: { query: { name: file.name, ...details } },
        headers: { "Content-Type": file.type || "application/octet-stream" },
        fetch: carrying(file),
      })
    ),
  changeLibraryFile: (id: number, values: Record<string, unknown>) =>
    answer(
      client.PUT("/api/library/{identifier}", { params: { path: { identifier: id } }, body: values })
    ),
  deleteLibraryFile: (id: number) =>
    answer(client.DELETE("/api/library/{identifier}", { params: { path: { identifier: id } } })),
  /** A file dropped in a conversation, kept in the library where it does not expire. */
  keepAttachment: (chat: string, id: string) =>
    answer(
      client.POST("/api/chat/{identifier}/attachments/{file}/keep", {
        params: { path: { identifier: chat, file: id } },
      })
    ),
  /** The skills given to the sessions — skills.py. Files travel as base64. */
  skills: () => answer(client.GET("/api/skills")),
  skill: (id: number) => answer(client.GET("/api/skills/{identifier}", { params: { path: { identifier: id } } })),
  addSkill: (values: Record<string, unknown>) => answer(client.POST("/api/skills", { body: values })),
  changeSkill: (id: number, values: Record<string, unknown>) =>
    answer(client.PUT("/api/skills/{identifier}", { params: { path: { identifier: id } }, body: values })),
  deleteSkill: (id: number) =>
    answer(client.DELETE("/api/skills/{identifier}", { params: { path: { identifier: id } } })),
  attachSkillFiles: (id: number, files: { path: string; data: string }[]) =>
    answer(client.POST("/api/skills/{identifier}/files", { params: { path: { identifier: id } }, body: { files } })),
  detachSkillFile: (id: number, path: string) =>
    answer(
      client.DELETE("/api/skills/{identifier}/file", { params: { path: { identifier: id }, query: { path } } })
    ),
  importSkill: (values: Record<string, unknown>) => answer(client.POST("/api/skills/import", { body: values })),
  /** Ponos's own vault, without a value: an admin's. */
  vault: () => answer(client.GET("/api/vault")),
  vaultHistory: (id: string) =>
    answer(client.GET("/api/vault/{entry_id}/history", { params: { path: { entry_id: id } } })),
  /* The writes: a value goes in and never comes back. `confirm` is the
   * password again, when the server asks for it (a 403 under `confirm`). */
  /** Ponos's browser: its profiles by project, and the browsers running now. */
  browser: () => answer(client.GET("/api/browser")),
  /** Forget everything a project's browser kept: every site signed out. */
  resetBrowser: (project: string) => answer(client.POST("/api/browser/reset", { body: { project } })),
  /** A browser on the project's profile, for somebody to drive from here: its id. */
  openBrowser: (project: string, url: string) =>
    answer(client.POST("/api/browser/live", { body: { project, url } })),
  /** One action played in a live browser: a click on its screen, some text, a key. */
  browserAct: (
    id: string,
    action: { action: "click" | "type" | "press" | "goto" | "scroll" | "close"; x?: number; y?: number; text?: string; key?: string; url?: string }
  ) =>
    answer(
      client.POST("/api/browser/live/{identifier}", {
        params: { path: { identifier: id } },
        body: { x: 0, y: 0, text: "", key: "", url: "", ...action },
      })
    ),
  createVaultEntry: (body: VaultNew) => answer(client.POST("/api/vault", { body })),
  changeVaultEntry: (id: string, body: VaultChange) =>
    answer(client.PUT("/api/vault/{entry_id}", { params: { path: { entry_id: id } }, body })),
  revokeVaultEntry: (id: string, confirm: string) =>
    answer(client.DELETE("/api/vault/{entry_id}", { params: { path: { entry_id: id } }, body: { confirm } })),
  /** Write the prompt run at every change of the ticket's status; empty removes it. */
  setOn: (id: string, on: string) =>
    answer(client.POST("/api/tickets/{ticket_id}/on", { params: { path: { ticket_id: id } }, body: { on } })),
  /** A run's last steps; `before`, those older than a position; `after`, those newer. */
  runSteps: (run: number, page: { before?: number; after?: number } = {}) =>
    answer(
      client.GET("/api/runs/{run}/steps", {
        params: {
          path: { run },
          query: page.after
            ? { after: String(page.after) }
            : page.before
              ? { before: String(page.before) }
              : {},
        },
      })
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
    /** The page of the goal it serves; empty for none. */
    goal?: string
    /** « Plan d'abord »: its first session proposes a plan and waits for a yes. */
    plan?: boolean
  }) =>
    answer(
      client.POST("/api/tickets", {
        body: { priority: "", type: "", model: "", subtype: "", on: "", goal: "", plan: false, attempts: 1, ...ticket },
      })
    ),
  /** `from` is the status the card showed: the board saying anything else by
   * the time the write goes out is somebody else's move, not overwritten. */
  setStatus: (id: string, column: string, from?: string) =>
    answer(
      client.POST("/api/tickets/{ticket_id}/status", {
        params: { path: { ticket_id: id } },
        body: { column, from },
      })
    ),
  tell: (id: string, text: string) =>
    answer(client.POST("/api/tickets/{ticket_id}/talk", { params: { path: { ticket_id: id } }, body: { text } })),
  /** What a blocked card, or one in review, offers to do about it. */
  decision: (id: string) =>
    answer(client.GET("/api/tickets/{ticket_id}/decision", { params: { path: { ticket_id: id } } })),
  decide: (
    id: string,
    choice: { key: string; number?: number; text?: string; model?: string; titles?: string[] }
  ) =>
    answer(
      client.POST("/api/tickets/{ticket_id}/decision", {
        params: { path: { ticket_id: id } },
        body: { number: 0, text: "", model: "", ...choice },
      })
    ),
  command: (line: string) => answer(client.POST("/api/command", { body: { line } })),
  send: (chat: string, text: string, attachments: string[] = []) =>
    answer(
      client.POST("/api/chat/{identifier}", {
        params: { path: { identifier: chat } },
        body: { text, attachments },
      })
    ),
  attach: (chat: string, file: File, name: string) =>
    answer(
      client.POST("/api/chat/{identifier}/attachments", {
        params: { path: { identifier: chat }, query: { name } },
        headers: { "Content-Type": file.type || "application/octet-stream" },
        fetch: carrying(file),
      })
    ),
  detach: (chat: string, id: string) =>
    answer(
      client.POST("/api/chat/{identifier}/attachments/{file}/remove", {
        params: { path: { identifier: chat, file: id } },
      })
    ),
  transcribe: (audio: Blob, language: string) =>
    answer(
      client.POST("/api/chat/transcribe", {
        params: { query: { lang: language } },
        headers: { "Content-Type": audio.type || "application/octet-stream" },
        fetch: carrying(audio),
      })
    ),
  /* The sentences of a reply worth saying aloud (the server drops code, tables
   * and markup); `final` false holds back a sentence still being written. */
  speakPlan: (text: string, language: string, final: boolean) =>
    answer(client.POST("/api/chat/speak/plan", { body: { text, lang: language, final } })),
  /* One sentence as a WAV, synthesised by Piper on the runner's machine. The
   * sound is not JSON, so it does not go through `answer`. */
  speak: async (text: string, language: string): Promise<ArrayBuffer> => {
    const { data, response, error } = await client.POST("/api/chat/speak", {
      body: { text, lang: language, final: true },
      parseAs: "arrayBuffer",
    })
    if (response.status === 401) backToTheDoor()
    if (!response.ok || !data) {
      const said = refusal(error)
      throw new ApiError(said.error || silent(response.status), response.status)
    }
    return data as ArrayBuffer
  },
  /** A new conversation, on the model of `like` (the one the page leaves). */
  newChat: (like = "") => answer(client.POST("/api/chat/new", { body: { like } })),
  sessions: (query = "") => answer(client.GET("/api/chat/sessions", { params: { query: { q: query } } })),
  renameSession: (id: string, title: string) =>
    answer(
      client.POST("/api/chat/{identifier}/rename", {
        params: { path: { identifier: id } },
        body: { title },
      })
    ),
  deleteSession: (id: string) =>
    answer(client.POST("/api/chat/{identifier}/delete", { params: { path: { identifier: id } } })),
  chatModels: (id = "") => answer(client.GET("/api/chat/models", id ? { params: { query: { id } } } : {})),
  setChatModel: (chat: string, model: string) =>
    answer(
      client.POST("/api/chat/{identifier}/model", { params: { path: { identifier: chat } }, body: { model } })
    ),
  linkSession: (id: string, project: string) =>
    answer(
      client.POST("/api/chat/{identifier}/project", {
        params: { path: { identifier: id } },
        body: { project },
      })
    ),
  stopChat: (chat: string) =>
    answer(client.POST("/api/chat/{identifier}/stop", { params: { path: { identifier: chat } } })),
  /** The answer has been seen: the conversation is no longer flagged unread. */
  readChat: (chat: string) =>
    answer(client.POST("/api/chat/{identifier}/read", { params: { path: { identifier: chat } } })),
  unqueue: (chat: string, id: string) =>
    answer(
      client.POST("/api/chat/{identifier}/queue/{waiting}/remove", {
        params: { path: { identifier: chat, waiting: id } },
      })
    ),
  amend: (chat: string, id: string, text: string) =>
    answer(
      client.POST("/api/chat/{identifier}/queue/{waiting}/edit", {
        params: { path: { identifier: chat, waiting: id } },
        body: { text },
      })
    ),
  releaseQueue: (chat: string) =>
    answer(client.POST("/api/chat/{identifier}/queue/send", { params: { path: { identifier: chat } } })),
  discardQueue: (chat: string) =>
    answer(client.POST("/api/chat/{identifier}/queue/discard", { params: { path: { identifier: chat } } })),
  saveSettings: (payload: {
    settings: Record<string, SettingValue>
    projects?: Pair[]
    github?: Pair[]
  }) => answer(client.POST("/api/settings", { body: payload })),
  saveContext: (text: string) => answer(client.POST("/api/context", { body: { text } })),
  saveProject: (id: string, values: Record<string, unknown>) =>
    answer(client.POST("/api/projects/{project_id}", { params: { path: { project_id: id } }, body: values })),
  saveProjectSettings: (
    id: string,
    values: {
      validation?: { own: boolean; values?: Partial<ProjectSettings["validation"]["values"]> }
      ideas?: { enabled: boolean }
      local_ci?: { enabled: boolean; command: string }
      self_review?: { enabled: boolean }
      setup?: { command: string }
      preview?: { command: string; url: string; pages: string[] }
      plan?: { priority: number | null; subtypes: string[] }
      browser?: { value: "ponos" | "chrome" }
      diagnostic?: Pick<ProjectSettings["diagnostic"], "mcp" | "hosts" | "urls" | "ready">
    }
  ) =>
    answer(
      client.POST("/api/projects/{project_id}/settings", { params: { path: { project_id: id } }, body: values })
    ),
  deleteProject: (id: string, values: { confirm: string; trash_tickets: boolean }) =>
    answer(
      client.POST("/api/projects/{project_id}/delete", { params: { path: { project_id: id } }, body: values })
    ),
  setPicture: (
    id: string,
    slot: "cover" | "icon",
    value: { url: string } | { emoji: string } | { remove: true }
  ) =>
    answer(
      client.POST("/api/projects/{project_id}/image/{slot}", {
        params: { path: { project_id: id, slot } },
        headers: { "Content-Type": "application/json" },
        fetch: carrying(JSON.stringify(value)),
      })
    ),
  uploadPicture: (id: string, slot: "cover" | "icon", file: Blob, name: string) =>
    answer(
      client.POST("/api/projects/{project_id}/image/{slot}", {
        params: { path: { project_id: id, slot } },
        headers: { "Content-Type": file.type, "X-Filename": encodeURIComponent(name) },
        fetch: carrying(file),
      })
    ),
  saveSchedule: (id: string, values: Record<string, unknown>) =>
    answer(
      client.POST("/api/schedules/{schedule_id}", { params: { path: { schedule_id: id } }, body: values })
    ),
  launchSchedule: (id: string) =>
    answer(client.POST("/api/schedules/{schedule_id}/launch", { params: { path: { schedule_id: id } } })),
  deleteSchedule: (id: string) =>
    answer(client.POST("/api/schedules/{schedule_id}/delete", { params: { path: { schedule_id: id } } })),
  createSchedule: (values: Record<string, unknown>) => answer(client.POST("/api/schedules", { body: values })),
  ideas: (project = "") =>
    answer(client.GET("/api/ideas", { params: { query: { project: project || undefined } } })),
  /** When ideas are found on their own, for which projects, and how the last pass went. */
  ideasPlan: () => answer(client.GET("/api/ideas/schedule")),
  /** The settings the dialog changed, and the ids of the projects ticked when only some are covered. */
  saveIdeasPlan: (values: Partial<IdeasSettings> & { projects?: string[] }) =>
    answer(client.POST("/api/ideas/schedule", { body: values })),
  /** An empty `project` is the workspace's ideas. */
  findIdeas: (project = "") => answer(client.POST("/api/ideas/generate", { body: { project } })),
  /** Every idea of one scope, thrown away and turned into tickets included. */
  allIdeas: (project = "", everywhere = false) =>
    answer(
      client.GET("/api/ideas/all", {
        params: { query: everywhere ? { scope: "all" } : { project: project || undefined } },
      })
    ),
  /** An idea written by hand; an empty `project` is the workspace's. */
  writeIdea: (values: {
    title: string
    description: string
    project: string
    kind?: Idea["kind"]
    category?: Idea["category"]
  }) => answer(client.POST("/api/ideas", { body: values })),
  editIdea: (id: number, values: { title: string; description: string; category?: Idea["category"] }) =>
    answer(client.POST("/api/ideas/{number}", { params: { path: { number: id } }, body: values })),
  /** Kept for later: nothing is written on the board. */
  keepIdea: (id: number) =>
    answer(client.POST("/api/ideas/{number}/keep", { params: { path: { number: id } } })),
  discardIdea: (id: number) =>
    answer(client.POST("/api/ideas/{number}/discard", { params: { path: { number: id } } })),
  /** A draft ticket — or, for the idea of a project, the project and its first ticket. */
  ticketIdea: (id: number) =>
    answer(client.POST("/api/ideas/{number}/ticket", { params: { path: { number: id } } })),
  reopenIdea: (id: number) =>
    answer(client.POST("/api/ideas/{number}/reopen", { params: { path: { number: id } } })),
  /** How many ideas have no score, and what scoring them may cost at most — said before it starts.
   * `project` null is every scope's, "" the workspace's. */
  unscoredIdeas: (project: string | null = null) =>
    answer(
      client.GET("/api/ideas/unscored", {
        params: { query: project === null ? { scope: "all" } : { project: project || undefined } },
      })
    ),
  /** Scores them, behind the answer: the list is told as each batch is done. */
  scoreIdeas: (project: string | null = null) =>
    answer(client.POST("/api/ideas/score", { body: project === null ? {} : { project } })),
  /** Takes back the last decision of one scope. */
  undoIdea: (project = "") => answer(client.POST("/api/ideas/undo", { body: { project } })),
  refresh: () => answer(client.POST("/api/refresh")),
  /** One notification read, or all of them; the bell it leaves is the answer. */
  readNotifications: (id?: number) =>
    answer(client.POST("/api/notifications/read", { body: id === undefined ? {} : { id } })),
  /** What is wrong with the installation: as checked a few minutes ago at most, or now when `fresh`. */
  health: (fresh = false) => answer(client.GET("/api/health", { params: { query: fresh ? { fresh } : {} } })),
  /** One fix a check offered — the page has asked first, and says so. */
  fixHealth: (action: string, target: string) =>
    answer(client.POST("/api/health/fix", { body: { action, target, confirmed: true } })),
  /** The console's key for Web Push, and the browsers the bell is pushed to. */
  push: () => answer(client.GET("/api/push")),
  /** This browser's subscription kept: the bell is pushed to it from now on. */
  subscribePush: (subscription: PushSubscriptionJSON, label: string) =>
    answer(
      client.POST("/api/push/subscribe", {
        body: {
          endpoint: subscription.endpoint ?? "",
          keys: { p256dh: subscription.keys?.p256dh ?? "", auth: subscription.keys?.auth ?? "" },
          label,
        },
      })
    ),
  unsubscribePush: (endpoint: string) => answer(client.POST("/api/push/unsubscribe", { body: { endpoint } })),
  /** One push to this browser, to see it arrive. */
  testPush: (endpoint: string) => answer(client.POST("/api/push/test", { body: { endpoint } })),
  disk: () => answer(client.GET("/api/disk")),
  clean: () => answer(client.POST("/api/disk/clean")),
  mcp: () => answer(client.GET("/api/mcp")),
  triggers: () => answer(client.GET("/api/triggers")),
  /* The answer holds the key: the only time it is said. */
  createTrigger: (values: Record<string, unknown>) => answer(client.POST("/api/triggers", { body: values })),
  revokeTrigger: (id: string) => answer(client.POST("/api/triggers/{hook_id}/revoke", { params: { path: { hook_id: id } } })),
  githubApps: () => answer(client.GET("/api/github")),
  saveGithubToken: (token: string) => answer(client.POST("/api/github/token", { body: { token } })),
  forgetGithubToken: () => answer(client.POST("/api/github/token/forget")),
  connectGithub: (organisation: string) =>
    answer(client.POST("/api/github/connect", { body: { organisation } })),
  disconnectGithub: (slug: string) => answer(client.POST("/api/github/disconnect", { body: { slug } })),
  /* Slow, and so its own call: Claude Code starts every server to see if it answers. */
  mcpServers: () => answer(client.GET("/api/mcp/servers")),
  testMcp: (target: "local" | "public") => answer(client.POST("/api/mcp/test", { body: { target } })),
  /* Nothing in the body: which version, and how it is installed, is the
   * server's to know. */
  upgrade: () => answer(client.POST("/api/update")),
  cancelUpgrade: () => answer(client.POST("/api/update/cancel")),

  /* The first connection. Its own state is asked without the door's reload:
   * a console nobody has claimed answers it to anybody, and a 401 there is an
   * answer to draw — the sign-in — not a page to leave. */
  setupState: async () => (await client.GET("/api/setup")).data ?? null,
  claim: (typed: { code: string; email: string; password: string; confirm: string; language?: string }) =>
    answer(client.POST("/api/setup", { body: typed })),
  summary: () => answer(client.GET("/api/setup/summary")),
  setupDone: () => answer(client.POST("/api/setup/done")),
  claudeLogin: () => answer(client.GET("/api/setup/claude")),
  /* `save: false` only tries the key — the settings' Test button — and writes nothing. */
  saveProvider: (chosen: { provider: string; key?: string; save?: boolean }) =>
    answer(client.POST("/api/setup/provider", { body: chosen })),
  setupProjects: () => answer(client.GET("/api/setup/projects")),
  startDemo: (chosen: { project: string; language: string }) =>
    answer(client.POST("/api/setup/demo", { body: chosen })),
  demo: (id: string) => answer(client.GET("/api/setup/demo", { params: { query: { id } } })),
  doctor: () => answer(client.GET("/api/setup/doctor")),
  serviceLog: () => answer(client.GET("/api/service-log")),
  github: () => answer(client.GET("/api/setup/github")),
  saveChannels: (typed: Record<string, string>) =>
    answer(client.POST("/api/setup/channels", { body: typed })),
}

/** The message of whatever went wrong, however it went wrong — in the page's language when it is one the server is known to say. */
export function why(error: unknown): string {
  return told(error instanceof Error ? error.message : String(error))
}

/* A refusal of the server in the page's language: the template it was said
 * from translated, and each value too — a setting's label is a sentence of
 * `french.ts` as well. See `refusals.ts`. */
function told(message: string): string {
  const refusal = refusalOf(message)
  if (!refusal) return message
  const params = Object.fromEntries(Object.entries(refusal.params).map(([name, value]) => [name, t(value)]))
  return t(refusal.key, params)
}
