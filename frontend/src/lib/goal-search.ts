/* What the Goals list keeps, and how far a goal has gone, without a DOM.
 *
 * Kept apart like `idea-search.ts`, so `node --test` reads it as it stands.
 * A goal's progress is the tickets that point at it, counted by column on the
 * server: a cancelled one is a ticket given up, not one left to do, so it is
 * out of the total — a goal whose last ticket was dropped is not short of one.
 *
 * The filters live in the address, as everywhere: "" is "all" for each, the
 * status as the goals database spells it, the project by its name. The status
 * is the exception, as the ideas' is: the list is opened to see what is being
 * worked toward, so "" is the active goals — no status, or one the server
 * counts as active —, and "all" is written in the address to see the met and
 * given-up ones too.
 */

/** The status filter's value for every goal; the address says nothing for the active ones, where the list rests. */
export const EVERY_STATUS = "all"

/** A goal, as much of it as the filters and the count read. */
export interface Counted {
  status?: string
  /** Whether the server counts its status as still worked toward; unsaid is active. */
  active?: boolean
  projects?: string[]
  tickets?: Record<string, number | undefined>
}

/** What the list is asked for: one status ("" for the active ones, "all" for every one), one project ("" for all). */
export interface GoalFilter {
  status?: unknown
  project?: unknown
}

/** "n of m tickets done": done, out of every ticket but those given up. */
export function progressOf(goal: Counted): { done: number; total: number } {
  let total = 0
  for (const [column, count] of Object.entries(goal.tickets ?? {}))
    if (column !== "cancelled") total += count ?? 0
  return { done: goal.tickets?.done ?? 0, total }
}

/** Whether the filters keep this goal. */
export function keeps(goal: Counted, filter: GoalFilter = {}): boolean {
  const status = String(filter.status ?? "")
  const project = String(filter.project ?? "")
  if (!status && goal.active === false) return false
  if (status && status !== EVERY_STATUS && (goal.status ?? "") !== status) return false
  if (project && !(goal.projects ?? []).includes(project)) return false
  return true
}

/** Every value a field takes among these goals, once each, in the order of a word list. */
export function valuesOf(goals: Counted[], field: "status" | "projects"): string[] {
  const seen = new Set<string>()
  for (const goal of goals) {
    const values = field === "status" ? [goal.status ?? ""] : (goal.projects ?? [])
    for (const value of values) if (value) seen.add(value)
  }
  return [...seen].sort((a, b) => a.localeCompare(b))
}

/** A due date as a day, in the reader's language — "31 Dec 2026"; what is not a date, as it was written. */
export function dueOf(due: string, locale: string): string {
  const day = /^\d{4}-\d{2}-\d{2}/.exec(due)?.[0]
  if (!day) return due
  const when = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(when.getTime())) return due
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(when)
}

/** The goals a ticket may be pointed at: those still worked toward, and the
 * one it already serves even once it is over — a choice that hid the current
 * value would draw it as none. Those of the ticket's project come first, the
 * rest in the order they came: "" for no project leaves the order alone. */
export function offeredTo<Goal extends { id: string; active?: boolean; project_ids?: string[] }>(
  goals: Goal[],
  project: string,
  current = ""
): Goal[] {
  const open = goals.filter((goal) => goal.active !== false || (current && goal.id === current))
  return projectFirst(open, project, (goal) => goal.project_ids ?? [])
}

/** These, those for the project first, each part in the order it came. */
export function projectFirst<Item>(items: Item[], project: string, projectsOf: (item: Item) => string[]): Item[] {
  if (!project) return items
  const mine = (item: Item) => projectsOf(item).includes(project)
  return [...items.filter(mine), ...items.filter((item) => !mine(item))]
}
