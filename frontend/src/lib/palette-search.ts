/* What the command palette keeps of what is typed into it, without a DOM.
 *
 * cmdk scores every entry it is given, fuzzily, at each key: on a board of
 * nearly two thousand tickets that is every one of them scored and drawn again
 * — over a second a letter — and a fuzzy score finds "Opoil" and "Portfolio"
 * for "obj". So the palette does its own filtering (`shouldFilter={false}`)
 * and hands cmdk only what this keeps: an entry is found when every word typed
 * is in it, the way the board's search finds a ticket (`ticket-search.ts`),
 * and no more than a screen of tickets, the open ones first.
 *
 * A ticket is folded once — its title and its project — and kept by the
 * object the board holds: the stream replaces a ticket that changed, so the
 * others are not folded again at the next key or the next event.
 */
import { fold, terms } from "./ticket-search.ts"

/** How many tickets the palette offers at once: past that, more letters narrow it. */
export const OFFERED = 20

/** Whether an entry, by its name and its keywords, says every word typed. */
export function says(texts: string[], words: string[]): boolean {
  if (!words.length) return true
  const said = fold(texts.join(" "))
  return words.every((word) => said.includes(word))
}

/** The little the palette reads of a ticket: `Ticket` has it, and so does a test. */
export interface Findable {
  short: string
  title: string
  column: string
  project: string
}

const folded = new WeakMap<Findable, string>()

function said(ticket: Findable): string {
  let text = folded.get(ticket)
  if (text === undefined) {
    text = fold(`${ticket.title} ${ticket.project}`)
    folded.set(ticket, text)
  }
  return text
}

const finished = (ticket: Findable) => ticket.column === "done" || ticket.column === "cancelled"

/* A word is in the title or the project, or starts the short id from four
 * characters on — as on the board: "a1" is somewhere in most ids. Finished
 * tickets come after the open ones, each in the board's order. */
export function ticketsFor<T extends Findable>(tickets: T[], text: string, limit = OFFERED): T[] {
  const words = terms(text)
  const found = (ticket: T) =>
    words.every(
      (word) => said(ticket).includes(word) || (word.length >= 4 && ticket.short.toLowerCase().startsWith(word))
    )
  const open: T[] = []
  const rest: T[] = []
  for (const ticket of tickets) {
    if (open.length >= limit) break
    if (!found(ticket)) continue
    if (!finished(ticket)) open.push(ticket)
    else if (rest.length < limit) rest.push(ticket)
  }
  return [...open, ...rest].slice(0, limit)
}
