import * as React from "react"
import { toast } from "sonner"

import { api, why } from "@/lib/api"
import { t } from "@/lib/i18n"
import { optimistic } from "@/lib/optimistic"
import { openChatId, setOpenChat, useOpenChat } from "@/lib/open-chat"
import type {
  Attached,
  ChatEvent,
  ChatSession,
  ChatState,
  CommandEvent,
  NoticeEvent,
  Queued,
  Role,
} from "@/lib/types"

/* Where the conversation this tab follows stands: a turn running or being
 * stopped, the queue said meanwhile, and what the transcript holds besides the
 * conversation itself.
 *
 * Several conversations can answer at once, and each tab follows its own
 * (`lib/open-chat.ts`). Every event of the stream names the conversation it is
 * about: those of the one followed move this state, the others only move
 * `elsewhere` — how many of the other conversations are answering, and how
 * many answered while nobody was looking.
 *
 * A click posts and says nothing here either: "sent", "stopping", "queue"
 * come back on the stream, to this tab and to the phone watching the same turn.
 */

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

/** The other conversations: how many answer now, and how many answered unseen. */
export interface Elsewhere {
  busy: number
  unread: number
  /** Turns running in every conversation, this one included: what the limit is counted against. */
  running: number
}

export interface Transcript {
  /** The conversation this tab follows: null until the server has said which. */
  chat: ChatState | null
  transcript: Entry[]
  /** A turn of the conversation followed is in flight. */
  busy: boolean
  /** A `>` command is running: one at a time, whatever the conversations are doing. */
  commanding: boolean
  /** The workspace's turn is being stopped: Stop was pressed, the end is on its way. */
  stopping: boolean
  /** Said while a turn ran, and not sent yet: the server's list, in order. */
  queue: Queued[]
  /** The turn ended before its time: the queue waits for Send or Discard. */
  held: boolean
  /** Messages wait and nothing runs: every place is taken by other conversations' turns. */
  limited: boolean
  elsewhere: Elsewhere
  /** Moves on each event about any conversation: what a list of them reads again on. */
  activity: number
  submit: (text: string, attachments?: Attached[]) => Promise<boolean>
  /** A new conversation, on the model of the one this tab leaves. */
  newChat: () => Promise<void>
  stopChat: () => Promise<void>
  runCommand: (line: string) => Promise<void>
  say: (role: Role, text: string) => void
}

let counter = 0
const nextId = () => ++counter

/** `reloadState`: the header read again, once a turn or a command is over. */
export function useTranscript(reloadState: () => Promise<void>) {
  const [transcript, setTranscript] = React.useState<Entry[]>([])
  const openId = useOpenChat()
  const [chat, setChat] = React.useState<ChatState | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [commanding, setCommanding] = React.useState(false)
  const [limited, setLimited] = React.useState(false)
  const [elsewhere, setElsewhere] = React.useState<Elsewhere>({ busy: 0, unread: 0, running: 0 })
  const [activity, setActivity] = React.useState(0)
  const [stopping, setStopping] = React.useState(false)
  const [queue, setQueue] = React.useState<Queued[]>([])
  const [held, setHeld] = React.useState(false)

  const say = React.useCallback((role: Role, text: string) => {
    setTranscript((entries) => [
      ...entries,
      { id: nextId(), at: Date.now(), kind: "turn", role, text },
    ])
  }, [])

  /* Where the followed conversation stands: a turn running, a queue waiting.
   * What was said in it is `useChat`'s, hydrated from the server (see
   * `lib/agui.ts`). Read again when this tab follows another one, or when the
   * one it followed was deleted — the commands run in the one before are not
   * this one's. */
  const adopt = React.useCallback((payload: ChatState) => {
    setTranscript([])
    setChat(payload)
    setBusy(Boolean(payload.busy))
    setStopping(Boolean(payload.stopping))
    setQueue(payload.queue ?? [])
    setHeld(Boolean(payload.held))
    setLimited(Boolean(payload.limited))
    if (payload.unread && payload.id) void api.readChat(payload.id).catch(() => {})
  }, [])

  const loadChat = React.useCallback(async () => {
    try {
      const wanted = openChatId()
      const payload = wanted ? await api.chat(wanted) : await api.latestChat()
      if (!wanted) setOpenChat(payload.id ?? "")
      else if (wanted !== openChatId()) return
      adopt(payload)
    } catch (error) {
      say("error", why(error))
    }
  }, [say, adopt])

  /* The state of the followed conversation without its transcript — a title, a
   * model — and the others' activity, read again behind an event. */
  const look = React.useRef<number | undefined>(undefined)
  const reloadChat = React.useCallback(async () => {
    const wanted = openChatId()
    if (!wanted) return
    try {
      const payload = await api.chat(wanted)
      if (wanted === openChatId()) setChat(payload)
    } catch {
      // The next event reads it again.
    }
  }, [])
  const watch = React.useCallback(() => {
    window.clearTimeout(look.current)
    look.current = window.setTimeout(() => {
      api
        .sessions("")
        .then(({ sessions }: { sessions: ChatSession[] }) => {
          const others = sessions.filter((item) => item.id !== openChatId())
          setElsewhere({
            busy: others.filter((item) => item.busy).length,
            unread: others.filter((item) => item.unread).length,
            running: sessions.filter((item) => item.busy).length,
          })
        })
        .catch(() => {})
    }, 250)
  }, [])

  React.useEffect(() => {
    void loadChat()
    watch()
  }, [openId, loadChat, watch])

  /** Says whether the line was taken, so the field is emptied only then: an
   * empty line is not, a refusal is not waited for. It is said by `say` and by
   * a toast, and the line is not put back. */
  const submit = React.useCallback(
    async (text: string, attachments: Attached[] = []) => {
      const line = text.trim()
      if (!line && !attachments.length) return false
      const command = line.startsWith(">")
      void optimistic({
        // A command is drawn by the stream as it starts, a message by `useChat`
        // or, when it waits for the turn to end, by the queue the stream sends.
        apply: () => {},
        request: async () => {
          if (command) await api.command(line.replace(/^\s*>/, ""))
          else
            await api.send(
              openChatId(),
              line,
              attachments.map((attachment) => attachment.id)
            )
        },
        rollback: (error) => say("error", why(error)),
        failure: command ? t("The command was not run") : t("The message was not sent"),
      })
      return true
    },
    [say]
  )

  const runCommand = React.useCallback(
    async (line: string) => {
      void optimistic({
        apply: () => {},
        request: () => api.command(line),
        rollback: (error) => say("error", why(error)),
        failure: t("The command was not run"),
      })
    },
    [say]
  )

  /* Stop says nothing here either: "stopping" and then "stopped" come back on
   * the stream, to this tab and to the phone that is watching the same turn. */
  const stopChat = React.useCallback(async () => {
    try {
      await api.stopChat(openChatId())
    } catch (error) {
      say("error", why(error))
    }
  }, [say])

  /* A new conversation is the tab's own business: the server makes it, on the
   * model of the one left, and the tab follows it. Nothing is interrupted — the
   * one left goes on answering. */
  const newChat = React.useCallback(async () => {
    void optimistic({
      apply: () => {},
      request: async () => {
        // Adopted from the answer itself, so that what is typed next is said in
        // the new conversation and not in the one being left.
        const fresh = await api.newChat(openChatId())
        adopt(fresh)
        setOpenChat(fresh.id ?? "")
      },
      rollback: (error) => say("error", why(error)),
      failure: t("The conversation was not started"),
    })
  }, [say, adopt])

  const on = {
    chat: (event: ChatEvent) => {
      // A step moves ten times a second and changes nothing a list shows.
      if (event.stage !== "step") {
        setActivity((count) => count + 1)
        watch()
      }
      if (event.id !== openChatId()) return
      if (event.stage === "deleted") {
        // The conversation followed is gone — here, in another tab, or by the assistant.
        setOpenChat("")
        return
      }
      if (event.stage === "renamed" || event.stage === "model") {
        void reloadChat()
        return
      }
      if (event.stage === "read") return
      if (event.stage === "queue") {
        setQueue(event.queue)
        setHeld(event.held)
        setLimited(event.limited)
        return
      }
      // What was said comes as AG-UI, to `useChat` (the `agui` events);
      // here, only whether a turn is running, and being stopped.
      if (event.stage === "sent") {
        setBusy(true)
        setStopping(false)
        setLimited(false)
        return
      }
      if (event.stage === "step") return
      if (event.stage === "stopping") {
        setStopping(true)
        return
      }
      // "answer", "failed" or "stopped": the turn is over, and this tab saw it.
      setBusy(false)
      setStopping(false)
      void api.readChat(event.id).catch(() => {})
      void reloadState()
      void reloadChat()
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
        setCommanding(true)
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
        setCommanding(false)
        void reloadState()
      }
    },

    // "notice", not "error": EventSource fires an `error` event of its own for
    // every dropped connection, and a server event under the same name would
    // arrive through the same listener with nothing in it.
    notice: (event: NoticeEvent) => {
      toast.error(event.where, { description: event.message })
      say("error", `${event.where}: ${event.message}`)
    },
  }

  const value = React.useMemo<Transcript>(
    () => ({
      chat,
      transcript,
      busy,
      commanding,
      stopping,
      queue,
      held,
      limited,
      elsewhere,
      activity,
      submit,
      newChat,
      stopChat,
      runCommand,
      say,
    }),
    [
      chat,
      transcript,
      busy,
      commanding,
      stopping,
      queue,
      held,
      limited,
      elsewhere,
      activity,
      submit,
      newChat,
      stopChat,
      runCommand,
      say,
    ]
  )

  return { value, on }
}
