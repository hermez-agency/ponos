import * as React from "react"
import { toast } from "sonner"

import { api } from "@/lib/api"
import { currentBoard, moveTicket, titleOf } from "@/lib/board-store"
import { t } from "@/lib/i18n"
import { optimistic } from "@/lib/optimistic"
import { ideasScored } from "@/lib/ideas-store"
import { goalsMoved } from "@/lib/goals-store"
import { publishBell } from "@/lib/notifications-store"
import type {
  AguiEvent,
  Bell,
  Board,
  ColumnKey,
  HealthReport,
  Project,
  Running,
  RunnerState,
  SyncEvent,
  Ticket,
} from "@/lib/types"
import { publishAgui } from "@/lib/agui"
import { useBoardFeed } from "./use-board-feed"
import { useCatchUp, type StepsValue } from "./use-catch-up"
import { greetUpdate, useRunner } from "./use-runner"
import { useStream, type Connection } from "./use-stream"
import { useTicketTalk, type TicketTalk } from "./use-ticket-talk"
import { useTranscript, type Transcript } from "./use-transcript"

export type { Session } from "./use-catch-up"
export type { Entry } from "./use-transcript"

/* Everything the console knows, in three places.
 *
 * The hand-written console kept a `state` object at the top of its single file
 * and mutated it. This is the same object, held by React so that the parts of
 * the page that care about a field redraw when it changes and the rest do not.
 *
 * Three contexts rather than one, because the fields do not move at the same
 * speed. A running session writes ten steps a second; the board moves every
 * few seconds at most; whether the stream is up and which sessions are running
 * changes a few times an hour. With one context, every step redrew the menu,
 * the board, the settings and the drawer — so the steps have a context of
 * their own, the connection and the list of sessions another, and the rest a
 * third, each value built once per change rather than once per render.
 *
 * The rule underneath is unchanged and is the reason this is a stream and not a
 * store: a click posts and says nothing. What lands here is what came back on
 * `/api/events`, so two open tabs agree, and an answer typed on a phone shows up
 * on the laptop without either of them asking.
 */

interface ConsoleValue extends Transcript, TicketTalk {
  board: Board
  runner: RunnerState | null
  projects: Project[]
  move: (ticket: Ticket, column: ColumnKey) => Promise<void>
  createTicket: (ticket: {
    title: string
    body: string
    project: string
    ready: boolean
  }) => Promise<void>
  refresh: () => Promise<void>
  reloadState: () => Promise<void>
}

/** Whether the stream is up, and which sessions are running. Slow to change. */
interface StatusValue {
  connection: Connection
  running: Running[]
}

const Context = React.createContext<ConsoleValue | null>(null)
const StatusContext = React.createContext<StatusValue | null>(null)
const StepsContext = React.createContext<StepsValue | null>(null)
/* When the board last agreed with Notion. Its own context: it changes on every
 * read, and nothing but the line that says it has to redraw for it. */
const SyncContext = React.createContext<SyncEvent | null>(null)

/* A card moved, and said so. Outside the provider's value on purpose: a card
 * reads the console's context for nothing else, and a context that changes
 * whenever a ticket is opened drew every card again with it. */
export async function moveWithToast(target: Ticket, column: ColumnKey) {
  const name =
    (column === "draft" ? t("Draft") : "") ||
    currentBoard()?.columns.find((item) => item.key === column)?.name ||
    column
  // The card is already in its column and the toast already says so: the
  // write goes out behind them, and a refusal puts the card back (see `moveTicket`).
  if (moveTicket(target.id, column, t("could not move “{{title}}”", { title: titleOf(target) })))
    toast.success(t("“{{title}}” moved to {{column}}", { title: titleOf(target), column: name }))
}

export function useConsole(): ConsoleValue {
  const value = React.useContext(Context)
  if (!value) throw new Error("useConsole outside its provider")
  return value
}

export function useStatus(): StatusValue {
  const value = React.useContext(StatusContext)
  if (!value) throw new Error("useStatus outside its provider")
  return value
}

/** `null` until the first read of the board has been said. */
export function useSync(): SyncEvent | null {
  return React.useContext(SyncContext)
}

export function useSteps(): StepsValue {
  const value = React.useContext(StepsContext)
  if (!value) throw new Error("useSteps outside its provider")
  return value
}

/* What the stream says that only goes on: to a store, or to whichever page
 * listens for it. Nothing here is the provider's state. */
const relayed = {
  // The bell: the runner wrote it, the server read it, this page only draws it.
  notifications: (event: Bell) => publishBell(event),

  // Scores the light model wrote behind the page: the lists of ideas read again.
  ideas: (event: { scored?: number; scoring?: number; failed?: string; planned?: number; settings?: boolean }) => {
    // A scheduled pass found some, or the schedule was changed: the lists and the banner read again.
    if (event?.planned !== undefined || event?.settings) window.dispatchEvent(new CustomEvent("ponos:ideas-plan"))
    if (event?.scored || event?.scoring || event?.planned) ideasScored()
    if (event?.failed) toast.error(t("The ideas could not be scored"), { description: event.failed })
  },

  // A goal written — here, in another tab, by the assistant — or a ticket tied to one.
  goals: () => goalsMoved(),

  // The schedules read again behind an answer, and something had changed: their lists read again.
  schedules: (event: { read?: boolean }) => {
    if (event?.read) window.dispatchEvent(new CustomEvent("ponos:schedules"))
  },

  // A turn of the conversation, as AG-UI: for the panel's `useChat`.
  agui: (event: AguiEvent) => publishAgui(event.event, event.thread),

  // The installation checked again behind an answer past its time (see
  // `Upkeep.health`): the band, wherever it is drawn, takes it if it is newer.
  health: (event: HealthReport) => window.dispatchEvent(new CustomEvent("ponos:health", { detail: event })),
}

/* Said at the click; the write goes out behind it, and a refusal is a toast. */
async function createTicket(fresh: { title: string; body: string; project: string; ready: boolean }) {
  void optimistic({
    apply: () => {},
    request: () => api.createTicket(fresh),
    rollback: () => {},
    failure: t("The ticket could not be created"),
    success: { title: t("Ticket created"), description: fresh.title },
  })
}

/* Two readings at once would be one too many, so the second click joins the
 * first rather than freezing the button until it ends. */
let rereading: Promise<boolean> | null = null

async function refresh() {
  rereading ??= optimistic({
    apply: () => {},
    request: () => api.refresh(),
    rollback: () => {},
    failure: t("The board could not be read again"),
    success: { title: t("Board read again") },
  }).finally(() => {
    rereading = null
  })
  void rereading
}

/* A gesture on a card. The card moves now, goes back if the write fails, and
 * says where it went — a ticket put on hold lands in a column that is often
 * off the screen, and a card that simply vanished reads as a card lost. */
const move = moveWithToast

/* Each part of what the console knows is a hook of its own, with the stream
 * handlers that feed it (`on`): the ticket open and its talk, the sessions and
 * their steps, the runner, the conversation, the board. Here they are only put
 * together, in the order they need each other. */
export function ConsoleProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = React.useState<Project[]>([])
  const [synced, setSynced] = React.useState<SyncEvent | null>(null)

  const talk = useTicketTalk()
  const sessions = useCatchUp(talk.value.ticket?.short ?? "")
  const { runner, reloadState, ...upkeep } = useRunner(sessions.catchUp)
  const chat = useTranscript(reloadState)
  const feed = useBoardFeed(talk.follow, () => askBoard())

  const readProjects = React.useCallback(() => {
    void api
      .projects()
      .then((payload) => setProjects(payload.projects))
      // A board with no projects database is a board that runs.
      .catch(() => {})
  }, [])

  const { connection, askBoard } = useStream({
    ...feed.on,
    ...sessions.on,
    ...relayed,
    ...chat.on,
    ...talk.on,
    ...upkeep.on,
    // A project was deleted — here, or from another tab, or by the assistant.
    // The names the ticket form offers are read again; the list reads itself.
    projects: readProjects,
    sync: (event: SyncEvent) => setSynced(event),
  })

  React.useEffect(() => {
    // The stream is already open by the time this runs, and only then the three
    // reads: two of them ask Notion, and a console that opened its live
    // connection *after* a slow board sat there saying "connecting…" for as long
    // as Notion took to answer.
    void reloadState()
    greetUpdate()
    readProjects()
  }, [reloadState, readProjects])

  const value = React.useMemo<ConsoleValue>(
    () => ({
      ...chat.value,
      ...talk.value,
      board: feed.board,
      runner,
      projects,
      move,
      createTicket,
      refresh,
      reloadState,
    }),
    [chat.value, talk.value, feed.board, runner, projects, reloadState]
  )

  const { running, live } = sessions
  const status = React.useMemo<StatusValue>(() => ({ connection, running }), [connection, running])

  return (
    <StatusContext.Provider value={status}>
      <SyncContext.Provider value={synced}>
        <StepsContext.Provider value={live}>
          <Context.Provider value={value}>{children}</Context.Provider>
        </StepsContext.Provider>
      </SyncContext.Provider>
    </StatusContext.Provider>
  )
}
