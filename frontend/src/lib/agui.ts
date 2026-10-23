import type { StreamChunk } from "@tanstack/ai"
import type { SubscribeConnectionAdapter, UIMessage } from "@tanstack/ai-react"

import { api } from "./api"

/* The conversation's connection, as TanStack AI's `useChat` wants one.
 *
 * `useChat` usually opens a stream per message: it posts, and reads the answer
 * off the response. The console's conversation is not the page's, though — it
 * is the server's, one for every tab and every phone, and a turn goes on when
 * the tab that started it is closed. So this is the other kind of connection
 * TanStack AI takes, the one that subscribes:
 *
 * - **subscribe** — the AG-UI events of every turn, whoever started it. They
 *   arrive on `/api/events` with everything else (`use-console` hands them
 *   here), and not on a stream of their own: a tab already holds one, and a
 *   second per tab would bring a few open tabs to the browser's limit of six
 *   connections to one server.
 * - **send** — the run, posted to `/api/chat/agui` as AG-UI's `RunAgentInput`.
 *   The server says the turn on the stream above, under the run id and the
 *   message id `useChat` chose, so the tab that sent it recognises its own.
 * - **hydrate** — the conversation as Ponos keeps it, from the same door: what
 *   `useChat` opens a conversation on, the one open or one of the history.
 *
 * Nothing here is TanStack's code: the types are, and they are gone once
 * built — which keeps this file in the first load, where `use-console` reads
 * it, and the package in the drawer's own chunk.
 */

type Listener = (event: StreamChunk) => void

const listeners = new Set<Listener>()

/** An AG-UI event off `/api/events`, for whichever conversation panel is open. */
export function publishAgui(event: unknown) {
  for (const listener of listeners) listener(event as StreamChunk)
}

async function* subscribe(signal?: AbortSignal): AsyncIterable<StreamChunk> {
  const waiting: StreamChunk[] = []
  let wake: (() => void) | null = null
  const listener: Listener = (event) => {
    waiting.push(event)
    wake?.()
  }
  const stop = () => wake?.()
  listeners.add(listener)
  signal?.addEventListener("abort", stop)
  try {
    while (!signal?.aborted) {
      const next = waiting.shift()
      if (next) {
        yield next
        continue
      }
      await new Promise<void>((resolve) => {
        wake = () => {
          wake = null
          resolve()
        }
      })
    }
  } finally {
    listeners.delete(listener)
    signal?.removeEventListener("abort", stop)
  }
}

export const connection: SubscribeConnectionAdapter = {
  subscribe,
  async send(messages, data, _signal, run) {
    await api.runChat({
      threadId: run.threadId,
      runId: run.runId,
      messages,
      // What a message carries besides its words: the ids of its files.
      forwardedProps: { ...data, ...run.forwardedProps },
    })
  },
  async hydrate(threadId) {
    const thread = await api.chatThread(threadId)
    return {
      messages: thread.messages as unknown as UIMessage[],
      activeRun: null,
      interrupts: null,
    }
  },
}

/** What Ponos alone knows about a message, in `metadata.ponos` (see `console.py`). */
export interface Ponos {
  role?: "you" | "workspace" | "error" | "stopped"
  at?: string
  attachments?: { id: string; name: string; kind: string; size: number }[]
  seconds?: number
  cost?: number
  error?: string
}

export const ponosOf = (message: UIMessage): Ponos =>
  ((message.metadata as { ponos?: Ponos } | undefined)?.ponos ?? {}) as Ponos
