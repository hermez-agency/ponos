/* Which schedules a search keeps, without a DOM.
 *
 * Kept apart like `project-search.ts`, so `node --test` reads it as it stands.
 * The words a schedule is found by are handed in — its rule already said in
 * the console's language, its project by name — so « lundi » finds the
 * Monday ones on a console in French.
 */

import { folded } from "./settings-search.ts"

/** The two states a schedule is in: it makes its tickets, or it is paused. */
export const STATES = ["on", "paused"] as const

/** What the list is asked for: the words typed, the project's page, and the state ("" for any). */
export interface ScheduleFilter {
  q?: unknown
  project?: unknown
  state?: unknown
}

/** One schedule, as the search reads it. */
export interface Findable {
  name: string
  active: boolean
  /** The page of the project it points at, and that project's name. */
  project_id: string
  project: string
  /** The rule, in the words the console says it in. */
  rule: string
}

/** Whether a search is on. */
export function filtering(filter: ScheduleFilter = {}): boolean {
  return [filter.q, filter.project, filter.state].some((value) => String(value ?? "").trim())
}

/** Whether a schedule is kept: every word is in its name, its project or its rule, and the project and the state are the ones asked for. */
export function keeps(schedule: Findable, filter: ScheduleFilter = {}): boolean {
  const project = String(filter.project ?? "").trim()
  if (project && schedule.project_id !== project) return false
  const state = String(filter.state ?? "").trim()
  if (state === "on" && !schedule.active) return false
  if (state === "paused" && schedule.active) return false
  const words = folded(String(filter.q ?? "")).split(/\s+/).filter(Boolean)
  const said = folded(`${schedule.name} ${schedule.project} ${schedule.rule}`)
  return words.every((word) => said.includes(word))
}
