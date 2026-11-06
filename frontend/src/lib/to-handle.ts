/* What waits for you, in the order a phone shows it — and which column of the board it opens on.
 *
 * On a phone the dashboard opens on the tickets you are the one to move: the
 * blocked ones and the ones in review (`to-handle.tsx`). The board under it
 * used to start 1 725 px down, and its Blocked column was the fourth, three
 * swipes to the right; what waited on an answer was counted in the menu's
 * badge and in the bell, and shown nowhere together.
 *
 * The order: a blocked ticket first — it waits on a word from you, a question
 * or an access — then a pull request to decide, and last the stops Ponos is
 * already on, which it tries again by itself or which wait for the base: they
 * may leave the column before you get to them (`series.ts`'s `handled`).
 * Inside each, the one waiting longest first: the date a ticket was last
 * touched is, for these, when it landed there.
 *
 * Plain data in and out, importing nothing, so that `node --test` reads it.
 */

/** As much of a ticket as the list reads. */
export interface Waiting {
  id: string
  column: string
  edited: string
  block?: { policy: string } | null
}

/** The columns whose tickets wait for you. */
export const WAITING = ["blocked", "review"] as const

/** Whether Ponos is already on a stop: it tries again by itself, or waits for the base to be green. */
const handled = (ticket: Waiting): boolean => {
  const policy = ticket.block?.policy ?? ""
  return policy.startsWith("retry:") || policy === "wait-base"
}

/** 0 a blocked ticket waiting on you, 1 one in review, 2 a stop Ponos is on; -1 nothing to handle. */
export function rankOf(ticket: Waiting): number {
  if (ticket.column === "review") return 1
  if (ticket.column !== "blocked") return -1
  return handled(ticket) ? 2 : 0
}

const time = (ticket: Waiting) => Date.parse(ticket.edited) || 0

/** The tickets to handle, in the order the list shows them. */
export function toHandle<T extends Waiting>(tickets: readonly T[]): T[] {
  return tickets
    .filter((ticket) => rankOf(ticket) >= 0)
    .sort((a, b) => rankOf(a) - rankOf(b) || time(a) - time(b))
}

/** The column a phone's board opens on, among those it draws: the one chosen last, while it is drawn, else Blocked, then In review, then the first with any card. */
export function openingColumn(columns: readonly string[], filled: ReadonlySet<string>, chosen?: string): string {
  if (chosen && columns.includes(chosen)) return chosen
  for (const key of WAITING) if (columns.includes(key) && filled.has(key)) return key
  return columns.find((key) => filled.has(key)) ?? columns[0] ?? ""
}
