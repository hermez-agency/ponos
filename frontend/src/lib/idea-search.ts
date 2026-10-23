/* Which ideas the filters of the Ideas list keep, without a DOM.
 *
 * Kept apart like `project-search.ts`, so `node --test` reads it as it stands.
 * The filters are the ones the list always had — the status, who wrote it, and
 * whom it is for — and the category it was sorted into. They live in the address, so every value is
 * a word a URL can carry: "" is "all", for each of them, and the workspace is
 * `workspace` rather than an empty project, which would mean "every project".
 * The status is the exception: the list is opened to sort the new ideas, so ""
 * is "new", and "all" is written in the address to look at every one.
 *
 * The counts beside the statuses are counted on what the other filters
 * keep, and not on the status itself: "Kept 3" says how many a click on it
 * would show.
 *
 * The score is one more filter, by its colour, and one order: the most relevant
 * first, the ideas not scored after every scored one. That order is where the
 * new ideas rest, since they are read to decide which to take; every other list
 * rests on the newest first, the order the server gives.
 */

/* Where a score turns green, and orange; under ORANGE it is red. The same two
 * numbers as `ideas.py` on the server — a test holds them equal. */
export const GREEN = 70
export const ORANGE = 40

/** A score's colour, and "unscored" for an idea with none. */
export const TONES = ["green", "orange", "red", "unscored"] as const
export type Tone = (typeof TONES)[number]

/** Green, orange or red by the two thresholds — "unscored" for an idea with no score. */
export function toneOf(score: number | null | undefined): Tone {
  if (score === null || score === undefined || Number.isNaN(score)) return "unscored"
  if (score >= GREEN) return "green"
  if (score >= ORANGE) return "orange"
  return "red"
}

/** How the list is ordered: the most relevant first, or the newest first. */
export const ORDERS = ["relevance", "newest"] as const
export type Order = (typeof ORDERS)[number]

export const STATUSES = ["proposed", "kept", "discarded", "ticket"] as const
export type Status = (typeof STATUSES)[number]

/** What an idea is about, one of them; an idea nobody sorted has "". */
export const CATEGORIES = ["ux", "feature", "security", "technical"] as const
export type Category = (typeof CATEGORIES)[number]

/** Who an idea is written by, as the filter says it. */
export const AUTHORS = ["ponos", "human"] as const

/** The project filter's value for the ideas of the workspace. */
export const WORKSPACE = "workspace"

/** The status filter's value for every idea; the address says nothing for the new ones, where the list rests. */
export const EVERY_STATUS = "all"

/** What the list is asked for: one status, one category, one author, one scope, one colour ("" for all of
 * each) — and an order, "" for the one the status rests on. The order is `sorted` rather than `order`,
 * which react-resource-view keeps for a sort of its own: one that outlives "Clear the search". */
export interface IdeaFilter {
  status?: unknown
  category?: unknown
  author?: unknown
  project?: unknown
  score?: unknown
  sorted?: unknown
}

/** One idea, as the filters read it. */
export interface Filterable {
  status: string
  kind: string
  category: string
  project: string
  author: { kind: string }
  /** Out of 100; none, or null, for an idea not scored. */
  score?: number | null
}

const said = (value: unknown) => String(value ?? "").trim()
export const bare = (id: string) => id.replace(/-/g, "")

/** Whom an idea is for: a project's bare id, or "" for the workspace — which an idea of a new project always is. */
export const scopeOf = (idea: Filterable) => (idea.kind === "project" ? "" : bare(idea.project))

/** The status the list shows: the one chosen, the new ideas when none is, "" for every idea. */
export function statusOf(filter: IdeaFilter = {}): string {
  const status = said(filter.status)
  if (status === EVERY_STATUS) return ""
  return status || "proposed"
}

/** Whether a filter other than the status is on: the status alone is not a search that found nothing. */
export function filtering(filter: IdeaFilter = {}): boolean {
  return Boolean(
    said(filter.status) || said(filter.category) || said(filter.author) || said(filter.project) || said(filter.score)
  )
}

/** Whether an idea is kept by the category, the author, the colour and the scope, whatever its status. */
export function around(idea: Filterable, filter: IdeaFilter = {}): boolean {
  const category = said(filter.category)
  if (category && idea.category !== category) return false
  const score = said(filter.score)
  if (score && toneOf(idea.score) !== score) return false
  const author = said(filter.author)
  if (author && idea.author.kind !== author) return false
  const project = said(filter.project)
  if (!project) return true
  return scopeOf(idea) === (project === WORKSPACE ? "" : bare(project))
}

/** Whether an idea is kept by every filter. */
export function keeps(idea: Filterable, filter: IdeaFilter = {}): boolean {
  const status = statusOf(filter)
  return around(idea, filter) && (!status || idea.status === status)
}

/** How many ideas each status button would show, and all of them. */
export function counts(ideas: Filterable[], filter: IdeaFilter = {}): Record<Status | "all", number> {
  const kept = ideas.filter((idea) => around(idea, filter))
  const counted = { all: kept.length } as Record<Status | "all", number>
  for (const status of STATUSES) counted[status] = kept.filter((idea) => idea.status === status).length
  return counted
}

/** The projects an idea is for, once each — the options of the project filter. */
export function scopes(ideas: Filterable[]): string[] {
  return [...new Set(ideas.map(scopeOf).filter(Boolean))]
}

/** The order a list is in: the one chosen, or the most relevant first for the new ideas and the newest otherwise. */
export function orderOf(filter: IdeaFilter = {}): Order {
  const chosen = said(filter.sorted)
  if ((ORDERS as readonly string[]).includes(chosen)) return chosen as Order
  return statusOf(filter) === "proposed" ? "relevance" : "newest"
}

/** The ideas in the list's order. The server's is the newest first; by relevance, the highest score first,
 * those not scored last, and the newest first among equals. */
export function ordered<T extends Filterable>(ideas: T[], filter: IdeaFilter = {}): T[] {
  if (orderOf(filter) === "newest") return ideas
  const rank = (idea: T) => (typeof idea.score === "number" ? idea.score : -1)
  return ideas
    .map((idea, position) => ({ idea, position }))
    .sort((a, b) => rank(b.idea) - rank(a.idea) || a.position - b.position)
    .map((one) => one.idea)
}
