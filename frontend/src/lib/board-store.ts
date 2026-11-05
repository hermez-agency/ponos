import * as React from "react"

import { api } from "./api"
import { t } from "./i18n"
import { optimistic } from "./optimistic"
import type { Board, BoardChanges, ColumnKey, Ticket } from "./types"

/* The board, as the stream last said it.
 *
 * react-resource-view asks a resource for its rows through `getCollection`,
 * and the natural thing to give it would be a request to `/api/board`. That
 * would ask Notion again every time the list redraws — while the stream is
 * already carrying the very same board every few seconds, to every open tab.
 * So the rows come from here: the stream writes, the resource reads, and a
 * redraw costs nothing.
 */

let board: Board | null = null
const listeners = new Set<() => void>()
const waiting: ((board: Board) => void)[] = []

const tell = () => listeners.forEach((listener) => listener())

/** What the stream just said. */
export function publishBoard(fresh: Board) {
  board = fresh
  for (const resolve of waiting.splice(0)) resolve(fresh)
  tell()
}

/** What moved since the board this page holds — the board it now holds, or
 * `null` when the changes do not follow from it (a version was missed) and
 * only the whole board will do.
 *
 * The tickets that did not change are kept as they were, the same objects, so
 * that only the cards that moved are drawn again. The server replays this very
 * function before sending (`difference` in `web/live.py`): change one, change
 * the other. */
export function applyChanges(changes: BoardChanges): Board | null {
  if (!board || board.version !== changes.base) return null
  const gone = new Set(changes.removed)
  for (const { ticket } of changes.changed) gone.add(ticket.id)
  const tickets = board.tickets.filter((ticket) => !gone.has(ticket.id))
  for (const { after, ticket } of changes.changed) {
    const at = after ? tickets.findIndex((item) => item.id === after) + 1 : 0
    if (after && !at) return null
    tickets.splice(at, 0, ticket)
  }
  board = { ...board, tickets, version: changes.version }
  tell()
  return board
}

/** A ticket as the console already knows it will be, before Notion confirms.
 *
 * A card dropped in a column has to land there now; the board event that
 * follows the write says the same thing a few seconds later. */
export function patchTicket(id: string, patch: Partial<Ticket>) {
  if (!board) return
  board = {
    ...board,
    tickets: board.tickets.map((ticket) => (ticket.id === id ? { ...ticket, ...patch } : ticket)),
  }
  tell()
}

/** A ticket just written, drawn before the board is reread. */
export function addTicket(ticket: Ticket) {
  if (!board || board.tickets.some((item) => item.id === ticket.id)) return
  board = { ...board, tickets: [...board.tickets, ticket] }
  tell()
}

export const currentBoard = (): Board | null => board

/* A ticket's title, or what to call one Notion left without: the server sends
 * it empty, and the words for "no title" are the console's, in its language. */
export const titleOf = (ticket: Pick<Ticket, "title">): string =>
  ticket.title || t("(untitled ticket)")

/* A card moved to another column: drawn there now, marked as waiting to be
 * sent, and put back where it was if the console refuses the move. The one way
 * a ticket changes column from the console — the buttons on a card and a card
 * dropped on the board both come through here, so neither can leave a card
 * standing in a column Notion never heard about.
 *
 * Nothing waits for the write (see `optimistic.ts`): it goes out behind the
 * card, which says "waiting" until the board the stream sends next says
 * otherwise — and that board says it failed, too, when it did. A refusal puts
 * the card back, unless the stream has already moved it somewhere else: the
 * stream is the truth. Says whether it moved anything. */
export function moveTicket(id: string, column: ColumnKey, failure = ""): boolean {
  const before = board?.tickets.find((ticket) => ticket.id === id)
  if (before && before.column === column) return false
  void optimistic({
    apply: () => {
      if (before) patchTicket(id, { column, sync: "pending", sync_error: "" })
    },
    request: () => api.setStatus(id, column, before?.status),
    rollback: () => {
      const now = board?.tickets.find((ticket) => ticket.id === id)
      if (before && now?.column === column && now.sync === "pending")
        patchTicket(id, {
          column: before.column,
          status: before.status,
          sync: before.sync,
          sync_error: before.sync_error,
        })
    },
    failure: failure || t("could not move the ticket"),
  })
  return true
}

/** A card drawn in place of another — the provisional one of a ticket being created, by its real one. */
export function replaceTicket(provisional: string, ticket: Ticket) {
  if (!board) return
  // The stream may have brought the real card before the answer did: it is the truth.
  const tickets = board.tickets.some((item) => item.id === ticket.id)
    ? board.tickets.filter((item) => item.id !== provisional)
    : board.tickets.map((item) => (item.id === provisional ? ticket : item))
  board = { ...board, tickets }
  tell()
}

/** A ticket taken off the board as drawn: a provisional card whose write was refused. */
export function dropTicket(id: string) {
  if (!board) return
  board = { ...board, tickets: board.tickets.filter((ticket) => ticket.id !== id) }
  tell()
}

/** The board, as soon as there is one. */
export function boardOnce(): Promise<Board> {
  if (board) return Promise.resolve(board)
  return new Promise((resolve) => waiting.push(resolve))
}

export function subscribeBoard(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/* What a project's card says of its tickets, by its name as a ticket carries
 * it: how many there are, how many wait, run or wait for a review, and when
 * the last of them changed.
 *
 * Counted here rather than asked of the server: `/api/projects` used to read
 * the whole tickets database again to say it, while every ticket was already
 * in this store. Counted once per board the stream sends, however many cards
 * ask. */
export interface Tally {
  count: number
  ready: number
  running: number
  review: number
  /** The latest `created` of its tickets, empty when none says. */
  created: string
  /** The latest `edited` of its tickets, empty when none says. */
  edited: string
}

let counted: { from: Board; tallies: Map<string, Tally> } | null = null

function talliesOf(from: Board): Map<string, Tally> {
  if (counted?.from !== from) {
    const tallies = new Map<string, Tally>()
    for (const ticket of from.tickets) {
      if (!ticket.project) continue
      const tally = tallies.get(ticket.project) ?? { count: 0, ready: 0, running: 0, review: 0, created: "", edited: "" }
      tally.count += 1
      if (ticket.column === "ready" || ticket.column === "running" || ticket.column === "review")
        tally[ticket.column] += 1
      // Compared as instants: a board of files may write them with an offset.
      if (Date.parse(ticket.edited) > (Date.parse(tally.edited) || 0)) tally.edited = ticket.edited
      if (Date.parse(ticket.created) > (Date.parse(tally.created) || 0)) tally.created = ticket.created
      tallies.set(ticket.project, tally)
    }
    counted = { from, tallies }
  }
  return counted.tallies
}

/** The same count, for what reads it outside a component: the order of the projects. */
export const currentTallies = (): Map<string, Tally> | null => (board ? talliesOf(board) : null)

/** The tickets of each project, by name — `null` until the first board arrives. */
export function useTicketTallies(): Map<string, Tally> | null {
  const held = React.useSyncExternalStore(subscribeBoard, () => board)
  return held ? talliesOf(held) : null
}

const EMPTY: Board = { tickets: [], columns: [] }

export function useBoard(): Board {
  return React.useSyncExternalStore(subscribeBoard, () => board ?? EMPTY)
}
