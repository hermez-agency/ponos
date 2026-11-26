/* Which projects a search keeps, without a DOM.
 *
 * Kept apart like `places.ts`, so `node --test` reads it as it stands. The
 * words a project is found by are handed in — its type already said in the
 * console's language — so « document » finds the documents on a console in
 * French as well as in English.
 */

import { folded } from "./settings-search.ts"

/** The two types a project has: it is worked on in git, or it is a document. */
export const KINDS = ["code", "document"] as const

/** What the list is asked for: the words typed, the type kept ("" for both),
 * and whether the archived projects are shown too — hidden while it says nothing. */
export interface ProjectFilter {
  q?: unknown
  type?: unknown
  archived?: unknown
}

/** One project, as the search reads it. */
export interface Findable {
  name: string
  kind: string
  /** The type, in the words the console says it in. */
  work: string
  /** Archived: put away, kept out of the list until it is asked for. */
  shelved?: boolean
}

/** Whether the filter asks for the archived projects too. */
export function showsArchived(filter: ProjectFilter = {}): boolean {
  const said = String(filter.archived ?? "").trim()
  return said !== "" && said !== "0" && said !== "false"
}

/** Whether a search is on. */
export function filtering(filter: ProjectFilter = {}): boolean {
  return Boolean(String(filter.q ?? "").trim() || String(filter.type ?? "").trim() || showsArchived(filter))
}

/** Whether a project is kept: every word is in its name or its type, the type is the one asked
 * for, and it is not archived — unless the archived ones are asked for. */
export function keeps(project: Findable, filter: ProjectFilter = {}): boolean {
  if (project.shelved && !showsArchived(filter)) return false
  const type = String(filter.type ?? "").trim()
  if (type && project.kind !== type) return false
  const words = folded(String(filter.q ?? "")).split(/\s+/).filter(Boolean)
  const said = folded(`${project.name} ${project.work} ${project.kind}`)
  return words.every((word) => said.includes(word))
}
