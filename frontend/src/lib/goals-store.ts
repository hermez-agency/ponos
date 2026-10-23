import type { Board } from "./types"

/* The goals, as the stream says they moved.
 *
 * A goal's progress is counted from its tickets, and the page that lists it
 * read it when it opened: a goal written in another tab, a ticket tied to one
 * from its window, a card of one dropped in Done — nothing this page did, so
 * nothing it waits on. The stream says `goals` after every write, and a move of
 * a card that serves one says it too; the goals read themselves again — here
 * rather than in `use-console`, which would otherwise import the resource
 * declarations, as the ideas have `ideas-store`.
 *
 * Gathered for a moment: a goal tied to five tickets is five events, and one
 * read says them all.
 */

const listeners = new Set<() => void>()
const QUIET = 300
let pending: ReturnType<typeof setTimeout> | null = null

/** Some goal changed, or how far it has gone: every page of them reads again, once. */
export function goalsMoved() {
  if (pending) clearTimeout(pending)
  pending = setTimeout(() => {
    pending = null
    listeners.forEach((listener) => listener())
  }, QUIET)
}

export function onGoalsMoved(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Whether going from one board to the next changes a goal's count: a ticket
 * that serves one came, went, changed column or changed goal — or reached
 * Notion, for a card this tab moved: drawn in its column before the write, it
 * changes column for the server only then. The first board changes nothing —
 * the goals were read with it. */
export function movesGoals(before: Board | null, after: Board): boolean {
  if (!before) return false
  const held = new Map(before.tickets.map((ticket) => [ticket.id, ticket]))
  for (const ticket of after.tickets) {
    const was = held.get(ticket.id)
    held.delete(ticket.id)
    if (!was) {
      if (ticket.goal_id) return true
      continue
    }
    if (!was.goal_id && !ticket.goal_id) continue
    if (was.goal_id !== ticket.goal_id || was.column !== ticket.column || was.sync !== ticket.sync) return true
  }
  return [...held.values()].some((ticket) => ticket.goal_id)
}
