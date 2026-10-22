/* The tickets waiting on you, one after another: the order they come in, and where to go next.
 *
 * Five blocked cards were five trips: open one, answer it, close it, find the
 * next on the board, open it. The series (`ticket-series.tsx`) holds them in
 * one window and walks through them; what it decides without a DOM — which
 * comes first, which is next once one is settled, what the address says — is
 * here, plain data in and out, so that `node --test` holds it to what it says.
 * Imports nothing, like `decision.ts`.
 *
 * The order is what can be settled at once first: a question, or a decision
 * the session left you (`session.question`), then an access only you can give
 * (`access.*`), then the rest — and last the stops Ponos is already on, the
 * ones it tries again by itself or that wait for the base to be green: they
 * may well leave the column before you get to them. Inside each, the highest
 * priority first, then the oldest.
 */

/** The two columns a series walks through: the blocked tickets, and the ones in review. */
export type SeriesColumn = "blocked" | "review"

/** As much of a ticket as the order reads. */
export interface Queued {
  id: string
  priority: number | null
  created: string
  block?: { code: string; policy: string } | null
}

/** What became of a ticket of the series: decided, or passed over for now. */
export type Outcome = "done" | "skipped"

/** The address's word for the series on screen: `?series=blocked`, over whatever page is under it. */
export const SERIES = "series"

/** How many cards a column needs before its heading offers to go through them. */
export const SERIES_FROM = 2

/** A priority nobody wrote is read as the board reads it: the middle. */
const MIDDLE = 50

/** Whether Ponos is already on the stop: it tries again by itself, or waits for the base. */
export const handled = (ticket: Queued): boolean => {
  const policy = ticket.block?.policy ?? ""
  return policy.startsWith("retry:") || policy === "wait-base"
}

/** The group a ticket comes in: 0 a question, 1 an access, 2 the rest, 3 what Ponos is on. */
export function groupOf(ticket: Queued): number {
  const code = ticket.block?.code ?? ""
  if (code === "session.question") return 0
  if (code.startsWith("access.")) return 1
  return handled(ticket) ? 3 : 2
}

const time = (ticket: Queued) => Date.parse(ticket.created) || 0

/** The tickets in the order the series takes them. */
export function ordered<T extends Queued>(tickets: T[]): T[] {
  return [...tickets].sort(
    (a, b) =>
      groupOf(a) - groupOf(b) ||
      (b.priority ?? MIDDLE) - (a.priority ?? MIDDLE) ||
      time(a) - time(b)
  )
}

/** The next ticket to show after `from`: the first not decided after it, else one not yet seen before it — or none, and the series is over. */
export function nextOf(ids: string[], outcomes: Record<string, Outcome>, from: string | null): string | null {
  const at = from === null ? -1 : ids.indexOf(from)
  const after = ids.slice(at + 1).find((id) => outcomes[id] !== "done")
  if (after) return after
  return ids.slice(0, Math.max(at, 0)).find((id) => outcomes[id] === undefined) ?? null
}

/** The ticket before `from` that can still be decided, if any. */
export function previousOf(ids: string[], outcomes: Record<string, Outcome>, from: string | null): string | null {
  const at = from === null ? ids.length : ids.indexOf(from)
  return (
    ids
      .slice(0, Math.max(at, 0))
      .reverse()
      .find((id) => outcomes[id] !== "done") ?? null
  )
}

/** How many were decided and how many passed over, among the tickets still in the series. */
export function tally(ids: string[], outcomes: Record<string, Outcome>): { done: number; skipped: number } {
  return {
    done: ids.filter((id) => outcomes[id] === "done").length,
    skipped: ids.filter((id) => outcomes[id] === "skipped").length,
  }
}

/** The series an address names, if it names one. */
export function seriesIn(search: string): SeriesColumn | null {
  const named = new URLSearchParams(search).get(SERIES)
  return named === "blocked" || named === "review" ? named : null
}

/** The same address, with the series on screen — or without one. Everything else in it is kept as it was written. */
export function withSeries(search: string, column: SeriesColumn | null): string {
  const kept = search
    .replace(/^\?/, "")
    .split("&")
    .filter((part) => part && !part.startsWith(`${SERIES}=`))
  if (column) kept.push(`${SERIES}=${column}`)
  return kept.length ? `?${kept.join("&")}` : ""
}
