/* What the search over the board decides, without a DOM to decide it in.
 *
 * The board and a project's page share one search bar (`ticket-search.tsx`),
 * and this is everything it decides: what a typed word is compared with, which
 * ticket a set of filters keeps, how the query is written into the address and
 * read back from it, where a found word sits in a title. Plain data in, plain
 * data out, and nothing imported, so that `node --test` reads it as it stands —
 * the way it reads `composer.ts`.
 *
 * Everything is done on the board the console already holds: the stream sends
 * every ticket, so a search is a filter over what is on the page, as fast as a
 * key. The brief is the one thing the board does not carry — it is a page of
 * blocks Notion sends one request at a time — so it is not searched; the
 * runner's line on the card (`progress`, the RESULT a run ended with) is, and
 * says what the brief came to.
 */

/** The switches that are not a property of their own. */
export type Flag = "pr" | "credits" | "sync"

/** How recently a ticket was created or touched. */
export type Period = "" | "today" | "7d" | "30d"

export interface TicketQuery {
  /** The words typed, as typed. */
  text: string
  /** The ticket's type, as the board's choices key it: `code`, `writing`… */
  type: string[]
  /** The column: `draft`, `ready`, `running`… */
  status: string[]
  priority: string[]
  model: string[]
  /** The project, by name: that is what a ticket carries. */
  project: string[]
  /** The goal, by its id: two goals may share a name, and a link names one. */
  goal: string[]
  /** Why a stopped ticket stopped, by its code in `blocks.py`: `merge.refused`… */
  block: string[]
  /** A code ticket's sub-type, by its key in `subtypes.py`: `bug`, `docs`… */
  subtype: string[]
  only: Flag[]
  /** At least this many dollars spent; 0 is any. */
  cost: number
  since: Period
}

export const EMPTY: TicketQuery = {
  text: "",
  type: [],
  status: [],
  priority: [],
  model: [],
  project: [],
  goal: [],
  block: [],
  subtype: [],
  only: [],
  cost: 0,
  since: "",
}

export const FLAGS: Flag[] = ["pr", "credits", "sync"]
export const PERIODS: Exclude<Period, "">[] = ["today", "7d", "30d"]
/** The thresholds offered for what a ticket cost. */
export const COSTS = [1, 5, 20]

/** The lists a query filters by, in the order the bar draws them. */
export const FACETS = ["type", "subtype", "status", "priority", "model", "project", "goal", "block"] as const
export type Facet = (typeof FACETS)[number]

/** The little the search reads of a ticket: `Ticket` has it, and so does a test. */
export interface Searchable {
  id: string
  short: string
  title: string
  column: string
  project: string
  type: string
  /** A score from 0 to 100, null on a board without the column. */
  priority: number | null
  model: string
  progress: string
  pull_request: string
  runner: string
  cost: number | null
  created: string
  edited: string
  held?: { reason: string; detail: string }
  sync?: string
  /** On a stopped ticket, its cause. */
  block?: { code: string } | null
  /** On a code ticket, its sub-type's key. */
  subtype?: string
  /** The goal it serves, by its id: "" for none. */
  goal_id?: string
}

/** One of the board's choices, the way `Board.choices` says it. */
export interface Choice {
  value: string
  label: string
}

/* -- words ---------------------------------------------------------------- */

/* One character, folded: lower case, without its accent, and anything that is
 * not a letter or a digit a space. "Rédaction" is found by "redaction", and
 * "petits-moteurs" — a branch, a file name — by "petits moteurs". */
function foldOne(character: string): string {
  const bare = character.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase()
  return /^[\p{L}\p{N}]+$/u.test(bare) ? bare : " "
}

/** A text as the search compares it: case, accents and punctuation set aside. */
export function fold(text: string): string {
  return Array.from(text, foldOne).join("").replace(/\s+/g, " ").trim()
}

/** The words of what was typed: each must be found, in any order. */
export function terms(text: string): string[] {
  return Array.from(new Set(fold(text).split(" ").filter(Boolean)))
}

/* A ticket named by what identifies it: the 32 characters of its page, which a
 * pasted Notion address ends with, or the eight of its short id, which a
 * branch (`ticket/…-d05cddf6`), a worktree and a card all end with. Pasted
 * whole, these find the one ticket rather than every title with "ticket" in it. */
function identifier(text: string): { id?: string; short?: string } {
  const whole = text.match(/(?:^|[^0-9a-f])([0-9a-f]{32})(?![0-9a-f])/i)
  if (whole) return { id: whole[1].toLowerCase() }
  // Typed alone, a short id is a word like any other, found by its start
  // (see `saysText`); at the end of a branch or a worktree, it is the ticket.
  const short = text.trim().match(/^\S*[-/]([0-9a-f]{8})$/i)
  return short && /\d/.test(short[1]) ? { short: short[1].toLowerCase() } : {}
}

/** Whether the words typed are said by the ticket. */
export function saysText(ticket: Searchable, text: string): boolean {
  const named = identifier(text)
  if (named.id) return ticket.id.replace(/-/g, "").toLowerCase() === named.id
  if (named.short) return ticket.short.toLowerCase() === named.short
  const words = terms(text)
  if (!words.length) return true
  const said = fold(
    [ticket.title, ticket.progress, ticket.pull_request, ticket.project, ticket.runner].join(" ")
  )
  const short = ticket.short.toLowerCase()
  // An id only by its start, and from four characters: "a1" is somewhere in
  // most ids, and finding every ticket for it is finding none.
  return words.every((word) => said.includes(word) || (word.length >= 4 && short.startsWith(word)))
}

/** The words worth marking on a card: none when the ticket was named by its id. */
export function marked(text: string): string[] {
  const named = identifier(text)
  return named.id || named.short ? [] : terms(text)
}

/* -- filters -------------------------------------------------------------- */

/* A ticket's choice against the ones asked for. The board spells a type as it
 * likes — "Rédaction" on a French board, "Writing" on another — and the query
 * keeps the key, so both are compared, folded. */
export function among(value: string, wanted: string[], choices: Choice[] = []): boolean {
  if (!wanted.length) return true
  const mine = fold(value)
  if (!mine) return false
  return wanted.some((key) => {
    if (fold(key) === mine) return true
    const choice = choices.find((candidate) => candidate.value === key)
    return Boolean(choice && fold(choice.label) === mine)
  })
}

const DAY = 24 * 60 * 60 * 1000

/** Since when a period reaches, from `now`: midnight for today. */
export function periodStart(period: Period, now: number): number {
  if (period === "today") {
    const midnight = new Date(now)
    midnight.setHours(0, 0, 0, 0)
    return midnight.getTime()
  }
  if (period === "7d") return now - 7 * DAY
  if (period === "30d") return now - 30 * DAY
  return 0
}

/** Whether a switch holds for the ticket. */
export function flagged(ticket: Searchable, flag: Flag): boolean {
  if (flag === "pr") return Boolean(ticket.pull_request)
  if (flag === "sync") return Boolean(ticket.sync)
  // Ready, and kept from starting by money: out of credit, at the reserve, or
  // past the day's budget — see `held` in `web/board.py`.
  return ["credits", "reserve", "budget"].includes(ticket.held?.reason ?? "")
}

export interface Context {
  /** The clock, for the period. */
  now: number
  /** The board's choices, to read a type's key as the board spells it. */
  choices?: Partial<Record<"type" | "model", Choice[]>>
}

/** A ticket's score as the query and the address say it: its digits, "" for none. */
export const scoreOf = (ticket: Searchable): string =>
  typeof ticket.priority === "number" ? String(ticket.priority) : ""

/** Whether a ticket is one the query asks for: every part of it, at once. */
export function matchesQuery(ticket: Searchable, query: TicketQuery, context: Context): boolean {
  const choices = context.choices ?? {}
  if (!among(ticket.type, query.type, choices.type)) return false
  if (query.status.length && !query.status.includes(ticket.column)) return false
  if (query.priority.length && !query.priority.includes(scoreOf(ticket))) return false
  if (!among(ticket.model, query.model, choices.model)) return false
  if (query.project.length && !query.project.includes(ticket.project)) return false
  if (query.goal.length && !query.goal.includes(ticket.goal_id ?? "")) return false
  if (query.block.length && !query.block.includes(ticket.block?.code ?? "")) return false
  if (query.subtype.length && !query.subtype.includes(ticket.subtype ?? "")) return false
  if (!query.only.every((flag) => flagged(ticket, flag))) return false
  if (query.cost > 0 && !((ticket.cost ?? 0) >= query.cost)) return false
  if (query.since) {
    const moved = Date.parse(ticket.edited || ticket.created) || 0
    if (moved < periodStart(query.since, context.now)) return false
  }
  return saysText(ticket, query.text)
}

/** Whether the query asks for anything. */
export function isEmpty(query: TicketQuery): boolean {
  return active(query) === 0 && !query.text.trim()
}

/** How many filters are on, the words aside: what the button that folds them away counts. */
export function active(query: TicketQuery): number {
  return (
    FACETS.reduce((sum, facet) => sum + (query[facet].length ? 1 : 0), 0) +
    query.only.length +
    (query.cost > 0 ? 1 : 0) +
    (query.since ? 1 : 0)
  )
}

/** One value of a list, on or off. */
export function toggled(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((one) => one !== value) : [...values, value]
}

/* -- the address ---------------------------------------------------------- */

/* The query lives in the address, one parameter per part, beside the ones the
 * console already writes there (`view`, `variant`, `tab`): a filtered board is
 * a link somebody can send, and a reload comes back to it. A list is its
 * values separated by commas, which a value therefore cannot hold — no type,
 * status or model does, nor a priority score. */
export const PARAMS = ["q", ...FACETS, "only", "cost", "since"] as const

const decode = (raw: string) => {
  try {
    return decodeURIComponent(raw.replace(/\+/g, " "))
  } catch {
    return raw
  }
}

/** The address's parameters, each as its key, its raw value, and the part it was written as. */
function parts(search: string): { key: string; raw: string; part: string }[] {
  return search
    .replace(/^\?/, "")
    .split("&")
    .filter(Boolean)
    .map((part) => {
      const at = part.indexOf("=")
      return at < 0 ? { key: part, raw: "", part } : { key: part.slice(0, at), raw: part.slice(at + 1), part }
    })
}

/** The query an address carries; anything it does not say is empty. */
export function readQuery(search: string): TicketQuery {
  const query: TicketQuery = {
    ...EMPTY,
    type: [],
    status: [],
    priority: [],
    model: [],
    project: [],
    goal: [],
    block: [],
    subtype: [],
    only: [],
  }
  for (const { key, raw } of parts(search)) {
    // Decoded before it is cut: the router writes the address again as it
    // reads it, and turns every comma into %2C on the way.
    const list = () => decode(raw).split(",").map((value) => value.trim()).filter(Boolean)
    if (key === "q") query.text = decode(raw)
    else if ((FACETS as readonly string[]).includes(key)) query[key as Facet] = list()
    else if (key === "only") query.only = list().filter((flag): flag is Flag => FLAGS.includes(flag as Flag))
    else if (key === "cost") query.cost = Math.max(0, Number(decode(raw)) || 0)
    else if (key === "since") {
      const period = decode(raw)
      query.since = PERIODS.includes(period as Exclude<Period, "">) ? (period as Period) : ""
    }
  }
  return query
}

/** The address with the query written in: its own parameters replaced, every other kept as it was. */
export function writeQuery(search: string, query: TicketQuery): string {
  const kept = parts(search)
    .filter(({ key }) => !(PARAMS as readonly string[]).includes(key))
    .map(({ part }) => part)
  const list = (values: string[]) => values.map(encodeURIComponent).join(",")
  const mine: string[] = []
  if (query.text.trim()) mine.push(`q=${encodeURIComponent(query.text.trim())}`)
  for (const facet of FACETS) if (query[facet].length) mine.push(`${facet}=${list(query[facet])}`)
  if (query.only.length) mine.push(`only=${list(query.only)}`)
  if (query.cost > 0) mine.push(`cost=${query.cost}`)
  if (query.since) mine.push(`since=${query.since}`)
  const all = [...kept, ...mine]
  return all.length ? `?${all.join("&")}` : ""
}

/* -- what is drawn -------------------------------------------------------- */

/**
 * Where the words are in a text, as `[start, end)` ranges of the text itself,
 * merged where they touch. Found on the folded text, character by character,
 * so "Rédaction" lights up whole for "redaction".
 */
export function marks(text: string, words: string[]): [number, number][] {
  if (!text || !words.length) return []
  // The folded text, and for each of its characters the one it came from.
  let folded = ""
  const from: number[] = []
  let at = 0
  for (const character of Array.from(text)) {
    const one = foldOne(character)
    for (let index = 0; index < one.length; index++) from.push(at)
    folded += one
    at += character.length
  }
  const found: [number, number][] = []
  for (const word of words) {
    let index = folded.indexOf(word)
    while (index >= 0) {
      const last = from[index + word.length - 1]
      const end = last + (Array.from(text.slice(last))[0]?.length ?? 1)
      found.push([from[index], end])
      index = folded.indexOf(word, index + 1)
    }
  }
  found.sort((a, b) => a[0] - b[0])
  const merged: [number, number][] = []
  for (const range of found) {
    const previous = merged[merged.length - 1]
    if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1])
    else merged.push([range[0], range[1]])
  }
  return merged
}
