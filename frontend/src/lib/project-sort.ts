/* In which order the projects are listed, without a DOM.
 *
 * Kept apart like `project-search.ts`, so `node --test` reads it as it stands.
 * The order lives in the address (`sort`, `dir`) next to the search, and an
 * empty value is the default: the projects somebody works on now come first,
 * which a list by name never said.
 */

/** What the projects can be ordered by. */
export const SORTS = ["created", "name", "count", "running"] as const
export type Sort = (typeof SORTS)[number]

/** What the order is asked for: the key and the direction ("" for the key's own). */
export interface ProjectOrder {
  sort?: unknown
  dir?: unknown
}

/** What the order reads of a project: its name, and what its tickets come to. */
export interface Sortable {
  name: string
  /** When its latest ticket was created; empty without a ticket. */
  created: string
  count: number
  /** Its tickets being worked on, now. */
  running: number
}

export const sortOf = (order: ProjectOrder = {}): Sort =>
  SORTS.find((sort) => sort === String(order.sort ?? "")) ?? "created"

/** A name reads upwards, a date or a count from the most. */
export const naturalDirection = (sort: Sort): "asc" | "desc" => (sort === "name" ? "asc" : "desc")

export function directionOf(order: ProjectOrder = {}): "asc" | "desc" {
  const asked = String(order.dir ?? "")
  return asked === "asc" || asked === "desc" ? asked : naturalDirection(sortOf(order))
}

/** Whether the order is anything but the default one. */
export const ordering = (order: ProjectOrder = {}): boolean =>
  sortOf(order) !== "created" || directionOf(order) !== "desc"

const byName = (a: Sortable, b: Sortable) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })

/** The key of a project, as a number; null where it has none and goes last whatever the direction. */
function keyOf(project: Sortable, sort: Sort): number | null {
  if (sort === "created") {
    const at = Date.parse(project.created)
    return Number.isNaN(at) ? null : at
  }
  if (sort === "count") return project.count || null
  if (sort === "running") return project.count ? project.running : null
  return null
}

/** The projects in the order asked for; ties, and projects without a ticket, by name. */
export function ordered<T extends Sortable>(projects: T[], order: ProjectOrder = {}): T[] {
  const sort = sortOf(order)
  const sign = directionOf(order) === "asc" ? 1 : -1
  return [...projects].sort((a, b) => {
    if (sort === "name") return sign * byName(a, b)
    const x = keyOf(a, sort)
    const y = keyOf(b, sort)
    if (x === null || y === null) return x === y ? byName(a, b) : x === null ? 1 : -1
    return x === y ? byName(a, b) : sign * (x - y)
  })
}
