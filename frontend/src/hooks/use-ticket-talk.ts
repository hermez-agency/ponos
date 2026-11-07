import * as React from "react"

import { api, why } from "@/lib/api"
import { t } from "@/lib/i18n"
import { optimistic } from "@/lib/optimistic"
import type { Message, TalkEvent, Ticket } from "@/lib/types"

/* The ticket open in its terminal, and what was said under it.
 *
 * Its own hook because the stream handlers of the board and of the talk read
 * which ticket is open without being rebuilt for it: the two refs below are
 * that, and nothing outside this file writes them.
 */

export interface TicketTalk {
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
}

export function useTicketTalk() {
  const [ticket, setTicket] = React.useState<Ticket | null>(null)
  const [talk, setTalk] = React.useState<Message[]>([])
  const [mention, setMention] = React.useState("")
  const [talkWaiting, setTalkWaiting] = React.useState(false)
  const [talkLoading, setTalkLoading] = React.useState(false)

  // What the stream handlers need to read without being rebuilt for it.
  const openId = React.useRef<string | null>(null)
  const openColumn = React.useRef<string>("")

  const loadTalk = React.useCallback(async (open: Ticket) => {
    setTalkLoading(true)
    try {
      const payload = await api.talk(open.id)
      // The board took a moment and you opened another card in it: this answer is
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
        drawn.current = []
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
    drawn.current = []
    setTicket(null)
    setTalk([])
    setTalkWaiting(false)
  }, [])

  const rereadTalk = React.useCallback(() => {
    if (ticket) void loadTalk(ticket)
  }, [ticket, loadTalk])

  /* What this page drew before the stream said it, oldest first, by identity.
   * The stream's version of the message replaces the first of them (it is the
   * truth: the server may have masked a password in it), so the message is
   * neither drawn twice nor lost; the phone that did not send it shows only
   * what came back on the stream. */
  const drawn = React.useRef<Message[]>([])

  const tell = React.useCallback(async (text: string) => {
    const id = openId.current
    const words = text.trim()
    if (!id || !words) return
    const local: Message = { role: "you", text: words, at: new Date().toISOString() }
    void optimistic({
      apply: () => {
        drawn.current.push(local)
        setTalk((messages) => [...messages, local])
        setTalkWaiting(false)
      },
      request: () => api.tell(id, words),
      rollback: () => {
        drawn.current = drawn.current.filter((message) => message !== local)
        setTalk((messages) => messages.filter((message) => message !== local))
      },
      failure: t("not written"),
    })
  }, [])

  /* The board moved: keep the open ticket's terminal describing the right
   * one. Reread the discussion only when the ticket *changed column* — that
   * is when a run ended and left its report under it. A ticket in flight
   * redraws the board every few seconds, and asking the board for its comments
   * each time would be polling a conversation that has not moved. The
   * "reread" button is there. */
  const follow = React.useCallback(
    (touched: Ticket[]) => {
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

  const on = {
    talk: (event: TalkEvent) => {
      // Somebody wrote to a ticket — here, or in the other tab, or on a phone.
      if (event.ticket !== openId.current) return
      const said: Message = { role: event.role, text: event.text, at: event.at }
      const mine = event.role === "you" ? drawn.current.shift() : undefined
      setTalk((messages) =>
        mine && messages.includes(mine)
          ? messages.map((message) => (message === mine ? said : message))
          : [...messages, said]
      )
      // An answer, from wherever it was typed, is the question answered.
      if (event.role === "you") setTalkWaiting(false)
    },
  }

  const value = React.useMemo<TicketTalk>(
    () => ({
      ticket,
      talk,
      mention,
      talkWaiting,
      talkLoading,
      openTicket,
      closeTicket,
      rereadTalk,
      tell,
    }),
    [ticket, talk, mention, talkWaiting, talkLoading, openTicket, closeTicket, rereadTalk, tell]
  )

  return { value, follow, on }
}
