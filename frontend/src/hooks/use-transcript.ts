import * as React from "react"
import { toast } from "sonner"

import { api, why } from "@/lib/api"
import { t } from "@/lib/i18n"
import { optimistic } from "@/lib/optimistic"
import type { Attached, ChatEvent, CommandEvent, NoticeEvent, Queued, Role } from "@/lib/types"

/* Where the workspace's conversation stands: a turn running or being stopped,
 * the queue said meanwhile, and what the transcript holds besides the
 * conversation itself.
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

export interface Transcript {
  transcript: Entry[]
  busy: boolean
  /** The workspace's turn is being stopped: Stop was pressed, the end is on its way. */
  stopping: boolean
  /** Said while a turn ran, and not sent yet: the server's list, in order. */
  queue: Queued[]
  /** The turn ended before its time: the queue waits for Send or Discard. */
  held: boolean
  submit: (text: string, attachments?: Attached[]) => Promise<boolean>
  resetChat: () => Promise<void>
  stopChat: () => Promise<void>
  runCommand: (line: string) => Promise<void>
  say: (role: Role, text: string) => void
}

let counter = 0
const nextId = () => ++counter

/** `reloadState`: the header read again, once a turn or a command is over. */
export function useTranscript(reloadState: () => Promise<void>) {
  const [transcript, setTranscript] = React.useState<Entry[]>([])
  const [busy, setBusy] = React.useState(false)
  const [stopping, setStopping] = React.useState(false)
  const [queue, setQueue] = React.useState<Queued[]>([])
  const [held, setHeld] = React.useState(false)

  const say = React.useCallback((role: Role, text: string) => {
    setTranscript((entries) => [
      ...entries,
      { id: nextId(), at: Date.now(), kind: "turn", role, text },
    ])
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
      await api.stopChat()
    } catch (error) {
      say("error", why(error))
    }
  }, [say])

  // The conversation is empty now; the stream's "reset" says the same.
  const resetChat = React.useCallback(async () => {
    void optimistic({
      apply: () => setTranscript([]),
      request: () => api.resetChat(),
      rollback: (error) => say("error", why(error)),
      failure: t("The conversation was not reset"),
    })
  }, [say])

  const on = {
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
      // What was said comes as AG-UI, to `useChat` (the `agui` events);
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
      transcript,
      busy,
      stopping,
      queue,
      held,
      submit,
      resetChat,
      stopChat,
      runCommand,
      say,
    }),
    [transcript, busy, stopping, queue, held, submit, resetChat, stopChat, runCommand, say]
  )

  return { value, loadChat, on }
}
