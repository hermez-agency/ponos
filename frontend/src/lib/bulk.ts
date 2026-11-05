/* What a selection of cards on the board can be told at once, decided without a DOM.
 *
 * An audit writes twenty to thirty-five tickets in one go, and each of them
 * used to be launched, set aside or ranked from its own card — on a phone, ten
 * drafts were ten « Make ready » and ten confirmations. The board now selects
 * cards (a box on hover, a long press on a touch screen, Shift for a run of
 * them, a box over a column for all of it) and one bar acts on all of them.
 *
 * Each gesture of the bar takes only the cards it means something for, and says
 * how many: a selection that mixes drafts and tickets in progress launches the
 * drafts and leaves the running ones alone, rather than refusing the lot. The
 * columns each one takes are those a card offers the same gesture in (see
 * `TicketActions`), narrowed where the card asks a question the bar cannot:
 * a blocked ticket the runner stopped on a question waits for its answer, and
 * only one set aside by hand — no cause on it — is launched again.
 *
 * Plain data in, plain data out, and nothing imported: `node --test` reads this
 * file as it stands, the way it reads `composer.ts`.
 */

/** What the bar reads of a ticket. */
export interface Selectable {
  id: string
  column: string
  /** Why the runner stopped on it; none for a ticket set aside by hand. */
  block?: unknown
  estimate?: { cost: number; cost_high: number } | null
}

/** The columns a ticket is in the runner's hands in: stopped from its card, not moved from a bar. */
const HELD = new Set(["running", "paused"])

/** Launched: a draft, a failed run, or a ticket set aside by hand. */
export function launchable(ticket: Selectable): boolean {
  if (ticket.column === "draft" || ticket.column === "failed") return true
  return ticket.column === "blocked" && !ticket.block
}

/** Set aside: what waits in Ready for the next pass. */
export const asideable = (ticket: Selectable): boolean => ticket.column === "ready"

/** Given up: anything not already given up and not in the runner's hands. */
export const cancellable = (ticket: Selectable): boolean =>
  ticket.column !== "cancelled" && !HELD.has(ticket.column)

/* What launching them is likely to cost: the sum of the estimates there are —
 * the median and the 80th centile of each — and how many have none. No
 * estimate is not a zero (see `ticket-estimate.tsx`): those are counted apart,
 * so the window says the sum is a floor. */
export function costOf(tickets: Selectable[]): { cost: number; high: number; estimated: number; unknown: number } {
  let cost = 0
  let high = 0
  let estimated = 0
  for (const ticket of tickets) {
    if (!ticket.estimate) continue
    cost += ticket.estimate.cost
    high += ticket.estimate.cost_high
    estimated += 1
  }
  return { cost, high, estimated, unknown: tickets.length - estimated }
}

/* The cards between the one clicked last and the one Shift-clicked, both in,
 * in the order the column draws them. Without a card clicked before, or when
 * either is no longer drawn there, only the one clicked: a run of cards from a
 * card that left the column would be a guess. */
export function rangeOf(order: string[], anchor: string | null, target: string): string[] {
  const to = order.indexOf(target)
  const from = anchor === null ? -1 : order.indexOf(anchor)
  if (to < 0) return [target]
  if (from < 0) return [target]
  const [low, high] = from < to ? [from, to] : [to, from]
  return order.slice(low, high + 1)
}

/** Whether a column's box is ticked, half-ticked, or not: all of its cards drawn are selected, some, or none. */
export function columnState(drawn: string[], selected: ReadonlySet<string>): boolean | "indeterminate" {
  const picked = drawn.filter((id) => selected.has(id)).length
  if (!picked) return false
  return picked === drawn.length ? true : "indeterminate"
}
