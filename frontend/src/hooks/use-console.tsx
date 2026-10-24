import * as React from "react"
import { toast } from "sonner"

import { api, why } from "@/lib/api"
import { applyChanges, currentBoard, moveTicket, publishBoard, titleOf } from "@/lib/board-store"
import { t } from "@/lib/i18n"
import { goalsMoved, movesGoals } from "@/lib/goals-store"
import { ideasScored } from "@/lib/ideas-store"
import { publishBell } from "@/lib/notifications-store"
import type {
  AguiEvent,
  Attached,
  Bell,
  Board,
  BoardChanges,
  ChatEvent,
  ColumnKey,
  CommandEvent,
  Message,
  NoticeEvent,
  Project,
  Queued,
  Role,
  Running,
  RunnerState,
  SessionsEvent,
  Step,
  StepEvent,
  SyncEvent,
  TalkEvent,
  Ticket,
  Upgrade,
  UpgradeProgress,
} from "@/lib/types"
import { publishAgui } from "@/lib/agui"
import { planOf, readPlan, type Task } from "@/lib/plan"
import { justUpdated, type UpgradePhase } from "@/lib/upgrade"
import { useStream, type Connection } from "./use-stream"

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

/** How many steps a session's panel keeps before it starts forgetting. */
const KEPT = 200

/** Where a page reloaded after an update leaves the version it came back on. */
const UPDATED = "ponos:updated"

/* What the console's transcript holds besides the conversation: the `>`
 * commands run from it and the problems it met on the way. The conversation
 * itself is `useChat`'s (see `ConsolePane`); these are drawn among its
 * messages by the time they were said — `at`, by this page's clock. */
export type Entry =
  | { id: number; at: number; kind: "turn"; role: Role; text: string }
  | {
      id: number
      at: number
      kind: "command"
      argv: string[]
      lines: string[]
      code: number | null
    }

export interface Session {
  source: string
  steps: Step[]
  /** How many steps the session has taken, the forgotten ones included. */
  count: number
  /** The agent's todo list as it stands; empty while it has not written one. */
  plan: Task[]
}

let counter = 0
const nextId = () => ++counter

interface ConsoleValue {
  board: Board
  runner: RunnerState | null
  projects: Project[]
  transcript: Entry[]
  busy: boolean
  /** The workspace's turn is being stopped: Stop was pressed, the end is on its way. */
  stopping: boolean
  /** Said while a turn ran, and not sent yet: the server's list, in order. */
  queue: Queued[]
  /** The turn ended before its time: the queue waits for Send or Discard. */
  held: boolean
  ticket: Ticket | null
  talk: Message[]
  mention: string
  /** The open ticket asked a question nobody has answered yet. */
  talkWaiting: boolean
  talkLoading: boolean
  openTicket: (ticket: Ticket) => void
  closeTicket: () => void
  rereadTalk: () => void
  tell: (text: string) => Promise<void>
  submit: (text: string, attachments?: Attached[]) => Promise<boolean>
  resetChat: () => Promise<void>
  stopChat: () => Promise<void>
  move: (ticket: Ticket, column: ColumnKey) => Promise<void>
  createTicket: (ticket: {
    title: string
    body: string
    project: string
    ready: boolean
  }) => Promise<void>
  refresh: () => Promise<void>
  runCommand: (line: string) => Promise<void>
  reloadState: () => Promise<void>
  say: (role: Role, text: string) => void
}

/** Whether the stream is up, and which sessions are running. Slow to change. */
interface StatusValue {
  connection: Connection
  running: Running[]
}

/** What the running sessions are doing. Changes with every step. */
interface StepsValue {
  sessions: Session[]
  /** The steps of the open ticket's session, if it has one this console saw. */
  ticketSteps: Step[]
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
  try {
    if (await moveTicket(target.id, column))
      toast.success(t("“{{title}}” moved to {{column}}", { title: titleOf(target), column: name }))
  } catch (error) {
    toast.error(t("could not move “{{title}}”", { title: titleOf(target) }), {
      description: why(error),
    })
  }
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

export function ConsoleProvider({ children }: { children: React.ReactNode }) {
  const [board, setBoard] = React.useState<Board>({ tickets: [], columns: [] })
  const [runner, setRunner] = React.useState<RunnerState | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [transcript, setTranscript] = React.useState<Entry[]>([])
  const [busy, setBusy] = React.useState(false)
  const [stopping, setStopping] = React.useState(false)
  const [queue, setQueue] = React.useState<Queued[]>([])
  const [held, setHeld] = React.useState(false)
  const [running, setRunning] = React.useState<Running[]>([])
  const [synced, setSynced] = React.useState<SyncEvent | null>(null)
  const [steps, setSteps] = React.useState<Record<string, Step[]>>({})
  // Counted apart from the steps kept: a card says how far a run has come,
  // and the panel forgets all but its last two hundred.
  const [counts, setCounts] = React.useState<Record<string, number>>({})
  // Kept apart too: the plan was written once, a long way back, and is the
  // one thing the last two hundred steps must not push out.
  const [plans, setPlans] = React.useState<Record<string, Task[]>>({})
  const [ticket, setTicket] = React.useState<Ticket | null>(null)
  const [talk, setTalk] = React.useState<Message[]>([])
  const [mention, setMention] = React.useState("")
  const [talkWaiting, setTalkWaiting] = React.useState(false)
  const [talkLoading, setTalkLoading] = React.useState(false)

  // What the stream handlers need to read without being rebuilt for it.
  const openId = React.useRef<string | null>(null)
  const openColumn = React.useRef<string>("")
  // The logs whose steps were already asked for, so a list announced twice
  // does not read the same log twice.
  const asked = React.useRef(new Set<string>())

  const say = React.useCallback((role: Role, text: string) => {
    setTranscript((entries) => [
      ...entries,
      { id: nextId(), at: Date.now(), kind: "turn", role, text },
    ])
  }, [])

  /* -- the sessions --------------------------------------------------------- */

  /* A session this page did not see start — the page was reloaded, or opened
   * mid-run — has its steps read back from its log, once, rather than
   * starting blank and filling from wherever it happened to be. */
  const catchUp = React.useCallback((sessions: Running[]) => {
    setRunning(sessions)
    for (const session of sessions) {
      if (asked.current.has(session.log)) continue
      asked.current.add(session.log)
      // Another run of the same ticket: the last one's plan is not this one's.
      setPlans(({ [session.source]: _, ...others }) => others)
      void api
        .log(session.log)
        .then((payload) => {
          const read = payload.steps.slice(-KEPT)
          const plan = planOf(payload.steps)
          if (plan.length) setPlans((current) => ({ ...current, [session.source]: plan }))
          // Steps that arrived on the stream while the log was being read are
          // in the log too: whichever says more is the one kept.
          setSteps((current) => {
            const seen = current[session.source] ?? []
            return seen.length >= read.length ? current : { ...current, [session.source]: read }
          })
          setCounts((current) =>
            (current[session.source] ?? 0) >= payload.count
              ? current
              : { ...current, [session.source]: payload.count }
          )
        })
        .catch(() => {
          // A log that cannot be read leaves the session to fill from the
          // stream, as it did before there was anything to catch up with.
        })
    }
  }, [])

  /* Where the open session stands: a turn running, a queue waiting. What was
   * said in it is `useChat`'s, hydrated from the server (see `lib/agui.ts`).
   * Also what a session opened, deleted or started in another tab leaves this
   * one to draw — the commands run in the one before are not this one's. */
  const loadChat = React.useCallback(async () => {
    try {
      const payload = await api.chat()
      setTranscript([])
      setBusy(Boolean(payload.busy))
      setStopping(Boolean(payload.stopping))
      setQueue(payload.queue ?? [])
      setHeld(Boolean(payload.held))
    } catch (error) {
      say("error", why(error))
    }
  }, [say])

  // The phase this page last saw, to tell a restart it watched from one it did not.
  const upgradePhase = React.useRef<UpgradePhase | undefined>(undefined)

  const reloadState = React.useCallback(async () => {
    try {
      const fresh = await api.state()
      setRunner(fresh)
      if (fresh.sessions) catchUp(fresh.sessions)
    } catch {
      // The header going stale is not worth a message: the stream is still up,
      // and the next event asks again.
    }
  }, [catchUp])

  /* -- the ticket's terminal ------------------------------------------------ */

  const loadTalk = React.useCallback(async (open: Ticket) => {
    setTalkLoading(true)
    try {
      const payload = await api.talk(open.id)
      // Notion took a moment and you opened another card in it: this answer is
      // about a ticket nobody is looking at any more.
      if (openId.current !== open.id) return
      setTalk(payload.messages)
      setMention(payload.mention)
      setTalkWaiting(Boolean(payload.waiting))
    } catch (error) {
      if (openId.current !== open.id) return
      setTalk([
        { role: "error", text: t("could not read the discussion: {{why}}", { why: why(error) }) },
      ])
    } finally {
      setTalkLoading(false)
    }
  }, [])

  const openTicket = React.useCallback(
    (open: Ticket) => {
      const another = openId.current !== open.id
      openId.current = open.id
      openColumn.current = open.column
      setTicket(open)
      if (another) {
        setTalk([])
        setTalkWaiting(false)
        void loadTalk(open)
      }
    },
    [loadTalk]
  )

  const closeTicket = React.useCallback(() => {
    openId.current = null
    openColumn.current = ""
    setTicket(null)
    setTalk([])
    setTalkWaiting(false)
  }, [])

  const rereadTalk = React.useCallback(() => {
    if (ticket) void loadTalk(ticket)
  }, [ticket, loadTalk])

  /* -- the stream ----------------------------------------------------------- */

  /* The board moved, whole or by a few tickets: `touched` are the tickets
   * that are new or changed, the only ones worth a look. */
  const boardMoved = React.useCallback(
    (fresh: Board, touched: Ticket[], before: Map<string, Ticket["sync"]>) => {
      // A move that did not reach Notion is said once, when it stops being on
      // its way — the card keeps saying it after the toast is gone.
      for (const item of touched) {
        if (item.sync !== "failed" && item.sync !== "conflict") continue
        if (before.get(item.id) === item.sync) continue
        toast.error(
          item.sync === "failed"
            ? t("“{{title}}” did not reach Notion", { title: titleOf(item) })
            : t("“{{title}}” was changed in Notion meanwhile", { title: titleOf(item) }),
          { description: item.sync_error }
        )
      }
      setBoard(fresh)
      // The board moved: keep the open ticket's terminal describing the right
      // one. Reread the discussion only when the ticket *changed column* — that
      // is when a run ended and left its report under it. A ticket in flight
      // redraws the board every few seconds, and asking Notion for its comments
      // each time would be polling a conversation that has not moved. The
      // "reread" button is there.
      const id = openId.current
      if (!id) return
      const moved = touched.find((item) => item.id === id)
      if (!moved) return
      const changed = moved.column !== openColumn.current
      openColumn.current = moved.column
      setTicket(moved)
      if (changed) void loadTalk(moved)
    },
    [loadTalk]
  )

  const syncs = () => new Map((currentBoard()?.tickets ?? []).map((item) => [item.id, item.sync]))

  const { connection, askBoard } = useStream({
    // Whole: on connecting, and when the columns changed.
    board: (fresh: Board) => {
      const before = syncs()
      if (movesGoals(currentBoard(), fresh)) goalsMoved()
      // The same board, where the resource views read it from.
      publishBoard(fresh)
      boardMoved(fresh, fresh.tickets, before)
    },

    // Only what moved since the last one. Changes that do not follow from the
    // board held here — one was lost on the way — are worth nothing: the whole
    // board is asked for again.
    changes: (changes: BoardChanges) => {
      const before = syncs()
      const held = currentBoard()
      const fresh = applyChanges(changes)
      if (!fresh) return askBoard()
      // A card of a goal changed column: the progress its page shows did too.
      if (movesGoals(held, fresh)) goalsMoved()
      boardMoved(
        fresh,
        changes.changed.map((entry) => entry.ticket),
        before
      )
    },

    // Which sessions are running: the server's word, not a count of the steps
    // this tab happened to see. A session that ended leaves the list here.
    sessions: (event: SessionsEvent) => catchUp(event.sessions ?? []),

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

    // A turn of the conversation, as AG-UI: for the panel's `useChat`.
    agui: (event: AguiEvent) => publishAgui(event.event),

    step: (event: StepEvent) => {
      const line: Step = { label: event.label, detail: event.detail, said: event.said }
      setSteps((current) => ({
        ...current,
        [event.source]: [...(current[event.source] ?? []), line].slice(-KEPT),
      }))
      setCounts((current) => ({ ...current, [event.source]: (current[event.source] ?? 0) + 1 }))
      if (event.label === "Plan") {
        const plan = readPlan(event.detail)
        if (plan.length) setPlans((current) => ({ ...current, [event.source]: plan }))
      }
    },

    chat: (event: ChatEvent) => {
      if (
        event.stage === "opened" ||
        event.stage === "deleted" ||
        event.stage === "renamed" ||
        event.stage === "model"
      ) {
        // Another session is the open one: its transcript replaces this one's.
        if (event.stage === "opened" || event.stage === "deleted") void loadChat()
        void reloadState()
        return
      }
      if (event.stage === "reset") {
        setTranscript([])
        void reloadState()
        setBusy(false)
        setStopping(false)
        setQueue([])
        setHeld(false)
        return
      }
      if (event.stage === "queue") {
        setQueue(event.queue)
        setHeld(event.held)
        return
      }
      // What was said comes as AG-UI, to `useChat` (the `agui` events below);
      // here, only whether a turn is running, and being stopped.
      if (event.stage === "sent") {
        setBusy(true)
        setStopping(false)
        return
      }
      if (event.stage === "step") return
      if (event.stage === "stopping") {
        setStopping(true)
        return
      }
      // "answer", "failed" or "stopped": the turn is over.
      setBusy(false)
      setStopping(false)
      void reloadState()
    },

    command: (event: CommandEvent) => {
      if (event.stage === "started") {
        setTranscript((entries) => [
          ...entries,
          {
            id: nextId(),
            at: Date.now(),
            kind: "command",
            argv: event.argv,
            lines: [],
            code: null,
          },
        ])
        setBusy(true)
        return
      }
      setTranscript((entries) => {
        const found = entries.findLastIndex(
          (entry) => entry.kind === "command" && entry.code === null
        )
        if (found < 0) return entries
        const entry = entries[found] as Extract<Entry, { kind: "command" }>
        const kept = [...entries]
        kept[found] =
          event.stage === "line"
            ? { ...entry, lines: [...entry.lines, event.text] }
            : { ...entry, code: event.code }
        return kept
      })
      if (event.stage === "ended") {
        setBusy(false)
        void reloadState()
      }
    },

    talk: (event: TalkEvent) => {
      // Somebody wrote to a ticket — here, or in the other tab, or on a phone.
      if (event.ticket !== openId.current) return
      setTalk((messages) => [...messages, { role: event.role, text: event.text, at: event.at }])
      // An answer, from wherever it was typed, is the question answered.
      if (event.role === "you") setTalkWaiting(false)
    },

    projects: () => {
      // A project was deleted — here, or from another tab, or by the assistant.
      // The names the ticket form offers are read again; the list reads itself.
      void api
        .projects()
        .then((payload) => setProjects(payload.projects))
        .catch(() => {})
    },

    settings: () => {
      // Another tab saved, or `ponos config` did. The settings pane
      // reloads itself when it is not in the middle of an edit; the header is
      // redrawn either way.
      window.dispatchEvent(new CustomEvent("ponos:settings"))
      void reloadState()
    },

    // "notice", not "error": EventSource fires an `error` event of its own for
    // every dropped connection, and a server event under the same name would
    // arrive through the same listener with nothing in it.
    sync: (event: SyncEvent) => setSynced(event),

    // An update's progress, from the click to the console coming back. The
    // process that answers after the restart is a new one: its first word is
    // `done`, and the header is read again for the version it runs.
    // The console's own check says so too, with what it found: the button
    // appears in every open page without one of them being reloaded.
    upgrade: (event: UpgradeProgress & Partial<Upgrade>) => {
      const before = upgradePhase.current
      upgradePhase.current = event.phase
      setRunner((current) =>
        current?.upgrade ? { ...current, upgrade: { ...current.upgrade, ...event } } : current
      )
      // The first one is the state the stream replays to every new connection,
      // which the header read at opening already holds: asked again, it was a
      // second /api/state at every load.
      if (before !== undefined && (event.phase === "done" || event.phase === "idle")) {
        void reloadState()
      }
      // The page itself is the old version's: once the console is back, it is
      // loaded again from the new one, and says so when it opens.
      if (justUpdated(before, event.phase)) {
        sessionStorage.setItem(UPDATED, event.target)
        window.location.reload()
      }
    },

    notice: (event: NoticeEvent) => {
      toast.error(event.where, { description: event.message })
      say("error", `${event.where}: ${event.message}`)
    },
  })

  /* -- what a click does ---------------------------------------------------- */

  /** Says whether the line was taken, so the field is emptied only then. */
  const submit = React.useCallback(
    async (text: string, attachments: Attached[] = []) => {
      const line = text.trim()
      if (!line && !attachments.length) return false
      try {
        if (line.startsWith(">")) await api.command(line.replace(/^\s*>/, ""))
        else
          await api.send(
            line,
            attachments.map((attachment) => attachment.id)
          )
        return true
      } catch (error) {
        say("error", why(error))
        return false
      }
    },
    [say]
  )

  const runCommand = React.useCallback(
    async (line: string) => {
      try {
        await api.command(line)
      } catch (error) {
        say("error", why(error))
      }
    },
    [say]
  )

  /* Stop says nothing here either: "stopping" and then "stopped" come back on
   * the stream, to this tab and to the phone that is watching the same turn. */
  const stopChat = React.useCallback(async () => {
    try {
      await api.stopChat()
    } catch (error) {
      say("error", why(error))
    }
  }, [say])

  const resetChat = React.useCallback(async () => {
    try {
      await api.resetChat()
    } catch (error) {
      say("error", why(error))
    }
  }, [say])

  const tell = React.useCallback(async (text: string) => {
    const id = openId.current
    if (!id || !text.trim()) return
    // Nothing is drawn here: what appears is what came back on the stream, so
    // the phone that sent it and the laptop that did not show the same thing.
    await api.tell(id, text.trim())
  }, [])

  /* A gesture on a card. The card moves now, goes back if the write fails, and
   * says where it went — a ticket put on hold lands in a column that is often
   * off the screen, and a card that simply vanished reads as a card lost. */
  const move = moveWithToast

  const createTicket = React.useCallback(
    async (fresh: { title: string; body: string; project: string; ready: boolean }) => {
      await api.createTicket(fresh)
      toast.success(t("Ticket created"), { description: fresh.title })
    },
    []
  )

  const refresh = React.useCallback(
    () =>
      api.refresh().then(
        () => void toast.success(t("Board read again")),
        (error) => void toast.error(t("The board could not be read again"), { description: why(error) })
      ),
    []
  )

  /* -- opening -------------------------------------------------------------- */

  React.useEffect(() => {
    // The stream is already open by the time this runs, and only then the three
    // reads: two of them ask Notion, and a console that opened its live
    // connection *after* a slow board sat there saying "connecting…" for as long
    // as Notion took to answer.
    void reloadState()

    // Reloaded by the update it watched (see `upgrade` below): said once, here.
    const updated = sessionStorage.getItem(UPDATED)
    if (updated !== null) {
      sessionStorage.removeItem(UPDATED)
      toast.success(t("Ponos is up to date"), {
        description: t("restarted on {{version}}", { version: updated }),
      })
    }

    void loadChat()

    void api
      .projects()
      .then((payload) => setProjects(payload.projects))
      // A board with no projects database is a board that runs.
      .catch(() => {})
  }, [reloadState, loadChat, say])

  const value = React.useMemo<ConsoleValue>(
    () => ({
      board,
      runner,
      projects,
      transcript,
      busy,
      stopping,
      queue,
      held,
      ticket,
      talk,
      mention,
      talkWaiting,
      talkLoading,
      openTicket,
      closeTicket,
      rereadTalk,
      tell,
      submit,
      resetChat,
      stopChat,
      move,
      createTicket,
      refresh,
      runCommand,
      reloadState,
      say,
    }),
    [
      board,
      runner,
      projects,
      transcript,
      busy,
      stopping,
      queue,
      held,
      ticket,
      talk,
      mention,
      talkWaiting,
      talkLoading,
      openTicket,
      closeTicket,
      rereadTalk,
      tell,
      submit,
      resetChat,
      stopChat,
      move,
      createTicket,
      refresh,
      runCommand,
      reloadState,
      say,
    ]
  )

  const status = React.useMemo<StatusValue>(() => ({ connection, running }), [connection, running])

  const openShort = ticket?.short ?? ""
  const live = React.useMemo<StepsValue>(
    () => ({
      sessions: running.map((session) => ({
        source: session.source,
        steps: steps[session.source] ?? [],
        count: counts[session.source] ?? steps[session.source]?.length ?? 0,
        plan: plans[session.source] ?? [],
      })),
      // Kept after the session ends: the open ticket's terminal shows how the
      // run it just finished went, until another ticket is opened.
      ticketSteps: openShort ? (steps[openShort] ?? []) : [],
    }),
    [running, steps, counts, plans, openShort]
  )

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
