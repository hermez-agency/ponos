import * as React from "react"
import {
  createRootRoute,
  createRouter,
  useLocation,
  type AnyRoute,
} from "@tanstack/react-router"
import { parseLink, type ViewResourceContextParams } from "react-resource-view"

/* The console's addresses.
 *
 * Everything the page shows is named in the query string, because the server
 * behind it is `http.server` and the standard library: `/` is the one page it
 * serves, and a deep path would be a 404 before the JavaScript had a chance
 * to read it. So the board is `/?view=console/tickets/list`, a ticket is
 * `/?view=console/tickets/read/<id>`, one section of the settings is
 * `/?view=console/settings/read/config/notify` — the shape react-resource-view
 * writes in its `query` routing mode.
 *
 * TanStack Router holds the history, and `react-resource-view/tanstack` is how
 * the views reach it. One route, the root: the package resolves the address
 * into a resource itself, and a route tree would say the same thing twice.
 */

/* The query string, handed back exactly as it was written.
 *
 * TanStack reparses the search into an object and writes it back out before
 * anybody reads `searchStr`. Its default writer would turn
 * `view=console/tickets/list` into `view=console%2Ftickets%2Flist` — and
 * react-resource-view says which menu entry is lit by comparing the address to
 * the links it built, character for character. So the string the object was
 * read from is kept beside it and is what goes back out — and an object the
 * router built itself is written the way the package writes, slashes left as
 * slashes. */
const written = new WeakMap<object, string>()

function parseSearch(searchStr: string): Record<string, string> {
  const search = Object.fromEntries(new URLSearchParams(searchStr))
  written.set(search, !searchStr || searchStr.startsWith("?") ? searchStr : `?${searchStr}`)
  return search
}

function stringifySearch(search: Record<string, unknown>): string {
  const kept = written.get(search)
  if (kept !== undefined) return kept
  const query = Object.entries(search)
    .filter(([, value]) => value !== undefined && value !== "")
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value)).replace(/%2F/gi, "/")}`)
    .join("&")
  return query ? `?${query}` : ""
}

/** The router, around whatever draws the page. */
export function consoleRouter(Shell: () => React.ReactNode) {
  const root: AnyRoute = createRootRoute({ component: Shell })
  return createRouter({ routeTree: root, parseSearch, stringifySearch })
}

/* -- what an address means ------------------------------------------------ */

/* A pane that has since become a resource, and the address it is now at.
 *
 * `/?page=projects` and `/?page=schedules` were pages of their own before those
 * two were lists you open a record from, and `/?page=live` and `/?page=context`
 * were until the console moved onto the package's admin layout (the context has
 * since become a page of its own again, with tabs, which is where it leads); a link
 * somebody bookmarked or pasted into a chat has to keep landing on them rather
 * than on the board. The live page has since gone altogether — a session is
 * followed on its ticket, and the running tickets are on the board — so
 * `/?page=live` leads to the board. Written out rather than generated: this
 * module is what the resources address themselves through, and importing one
 * from here would be a circle.
 */
const MOVED: Record<string, string> = {
  projects: "/?view=console/projects/list",
  schedules: "/?view=console/schedules/list",
  live: "/?view=console/tickets/list",
  context: "/?view=console/context/read/context",
}

/** Where an old address now leads, if it is one. */
export function movedFrom(searchStr: string): string | undefined {
  return MOVED[new URLSearchParams(searchStr).get("page") ?? ""]
}

/** The address bar, as the resource it names. */
export function useRoute(): { params: ViewResourceContextParams; moved?: string } {
  const { pathname, searchStr } = useLocation()
  return React.useMemo(
    () => ({ params: parseLink(pathname + searchStr), moved: movedFrom(searchStr) }),
    [pathname, searchStr]
  )
}
