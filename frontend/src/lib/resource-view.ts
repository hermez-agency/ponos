import * as React from "react"
import { ActionList } from "react-data-form"
import {
  configureApi,
  configurePorts,
  configureResourceView,
  generateLinkByResource,
  parseLink,
  setCurrentScope,
  useCurrentViewResourceContext,
  useLocation,
  useNavigate,
  type ApiDialectInterface,
  type LinkPropsInterface,
} from "react-resource-view"
import { tanstackAdapter } from "react-resource-view/tanstack"

import { Pagination } from "@/components/console/pagination"

import { readQuery, writeQuery } from "./ticket-search"

// The dictionary has to be in place before a resource is declared: the words
// the views are built with go through it. See `i18n.ts`, which applies it on
// import.
import { onLanguageChange } from "./i18n"

/* Wiring react-resource-view into the console, once, before a resource is
 * declared — `createViewResource` reads the dialect as it builds.
 *
 * The package knows neither this router nor this API; both arrive here — the
 * router through the adapter the package ships for TanStack Router. The
 * API side is small: every resource brings its own reads and writes (the
 * board comes off the stream, a ticket off `/api/tickets/<id>`), so the
 * dialect's only real job is to say what a ticket's identity is — the bare
 * page id, which is also the segment a URL carries.
 */

/** Every resource of the console lives under this scope, which is the first segment of every address. */
export const SCOPE = "console"

const ticketDialect: ApiDialectInterface = {
  name: "ponos",
  buildRequest(operation) {
    // Every resource declares its own reads and writes; nothing builds a
    // request from the path alone.
    throw new Error(`no request for ${operation.name} on ${operation.path}`)
  },
  readCollection(payload) {
    const collection = (payload ?? {}) as { items?: unknown[]; member?: unknown[] }
    const items = (collection.items ?? collection.member ?? []) as Record<string, unknown>[]
    return { items, totalItems: items.length }
  },
  readItem: (payload) => (payload ?? undefined) as Record<string, unknown> | undefined,
  getId: (item) => (item?.id as string | undefined) ?? undefined,
  getIdentifier: (item) => (item?.id as string | undefined) ?? undefined,
  normalizeError(payload, status) {
    // `violations` is how a form is told which field a refusal is about: the
    // message is then drawn under that field rather than only in a toast.
    const said = payload as
      | { error?: string; violations?: { propertyPath?: string; message?: string }[] }
      | undefined
    return { status, detail: said?.error, violations: said?.violations }
  },
  referencesAreIris: false,
}

let done = false

export function configureConsoleViews() {
  if (done) return
  done = true

  setCurrentScope(SCOPE)

  configurePorts({
    navigation: { ...tanstackAdapter, Link: CarryingLink },
    // The one page the Python server serves is `/`; the rest is the query
    // string, so a deep link survives a reload.
    routing: { mode: "query", param: "view", basePath: "/" },
    appName: "Ponos",
    // `index.html` names the page; the views are not to rename it.
    ownsDocumentHead: false,
    isDev: false,
  })

  configureApi({ baseUrl: "", dialect: ticketDialect })

  declareDefaults()
  onLanguageChange(declareDefaults)
}

/* What every view of the console has in common, under each declaration.
 *
 * The pages of a list in the console's words rather than the package's, which
 * still writes "Showing 1 to 30 sur 475 results" whatever the language.
 *
 * Said again whenever the language changes, and that is the other half of
 * it: react-resource-view 1.0 merges a declaration into its views once, as
 * the resource is declared, and copies every field of a form as it does — so a
 * `get description()` that reads the dictionary is read then, in the language
 * of that moment. Defaults said again are the package's own way of building
 * every resource anew, and the getters are read again with them. */
function declareDefaults() {
  configureResourceView({
    defaults: {
      components: { pagination: Pagination },
      // react-resource-view 2.2 draws a "Shown fields" menu over every list;
      // the console offers it where a list says so — the board's List.
      views: { list: { fields: { toggle: false } } },
    },
  })
}

// On import, so that a resource declared in any module finds the dialect in place.
configureConsoleViews()

/* -- what a creation starts with ------------------------------------------- */

/* A creation opened in a frame over a page, with what it starts with.
 *
 * react-resource-view 1.0 writes the address of a frame from the view it opens
 * over, and leaves out what the creation starts with, which is the frame's own:
 * a new ticket made from a project's tickets, or from its card, opened with no
 * project in it. So the link to a creation in a frame that says nothing of it
 * carries what it starts with — the one it is given, or the list's it is drawn
 * in (a project's tickets start with the project) — the way the package
 * already writes it for a creation on a page of its own, and reads it back. */
export function carrying(to: string, data: object | undefined): string {
  if (!data || !Object.keys(data).length) return to
  if (new URLSearchParams(to.split("?")[1] ?? "").has("defaultData")) return to
  if (parseLink(to).childViewResource?.resourceAction !== ActionList.create) return to
  return `${to}${to.includes("?") ? "&" : "?"}defaultData=${encodeURIComponent(JSON.stringify(data))}`
}

/** The router's link, for the views: see `carrying`. */
function CarryingLink(props: LinkPropsInterface) {
  const context = useCurrentViewResourceContext()
  return React.createElement(tanstackAdapter.Link, {
    ...props,
    to: carrying(props.to, context?.defaultData),
  })
}

/* -- the layout a list is drawn in ---------------------------------------- */

/* The layout you picked, written into the address.
 *
 * The package's tabs move the layout on the context and nowhere else, so the
 * table you switched to was gone on the next reload — and gone again on the way
 * back from a record, since that link is built from the list and knew nothing
 * of it. The address already knows how to carry a layout: `variant=` is what
 * `generateLinkByResource` writes and what the package reads on the way in.
 * What was missing is somebody writing it there.
 *
 * Written here rather than in one resource because both lists have two layouts
 * and the same thing was true of both: the board opens on its cards whatever
 * you were last comparing tickets in.
 */
const layouts = new Map<string, string>()

/** The layout a list was last worked in, for the links that lead back to it. */
export const layoutOf = (resourceId: string): string | undefined =>
  layouts.get(resourceId) || undefined

/**
 * Keep the address in step with the layout tab, and remember it.
 *
 * Replaced rather than pushed: picking a layout is not a step you go back
 * through. And left alone until you pick something other than the first one, so
 * a link shared as `/?view=console/tickets/list` stays what somebody typed.
 */
export function useLayoutInTheAddress(resourceId: string): void {
  const { view, viewVariant, resource, resourceAction, setViewResource } =
    useCurrentViewResourceContext()
  const first = view?.layouts?.[0]?.id
  const listing = resourceAction === ActionList.list
  // The address as the router has it, not as `window.location` has it: a
  // navigation through TanStack lands a moment after it is asked for, and an
  // address read in between would ask for the same layout again, forever.
  const carried = new URLSearchParams(useLocation().searchStr).get("variant")
  const navigate = useNavigate()
  const latest = React.useRef(navigate)
  latest.current = navigate
  React.useEffect(() => {
    // A `top` declared on the resource's view is drawn over its record too, and
    // there the variant is whatever the declaration lists first: left to run, a
    // ticket opened from the table would forget the table on its way in.
    if (!listing || !viewVariant) return
    // Back from a record through the layout's own header, whose link to the
    // list knows no layout: the one it was left in is put back — the way its
    // tab would, on the context, which is what the address is then written
    // from — rather than taken for a choice of the first. A tab opened on a
    // bare address has nothing remembered, and stays on what was typed.
    const left = layouts.get(resourceId)
    if (!carried && viewVariant === first && left) {
      setViewResource((current) => ({ ...current, viewVariant: left }))
      return
    }
    // Kept here as well as in the address, because the pages that link back to
    // a list — a record, the sidebar — have an address of their own to read and
    // would otherwise send everybody back to the first layout.
    layouts.set(resourceId, viewVariant === first ? "" : viewVariant)
    if (carried === viewVariant || (!carried && viewVariant === first)) return
    const [path, search = ""] = generateLinkByResource({
      resource,
      resourceAction: ActionList.list,
      viewVariantId: viewVariant,
    }).split("?")
    // A search on the board is still on in the table: its words go along.
    const searched = readQuery(window.location.search)
    void latest.current({ to: `${path}${writeQuery(`?${search}`, searched)}`, replace: true })
  }, [listing, resourceId, viewVariant, first, resource, carried, setViewResource])
}

/**
 * Remember the layout of a list drawn inside another page, and nothing else.
 *
 * The list under a project's tickets is the board's list, so the layout picked
 * there is the one the board opens on, and the other way round. It leaves the
 * address alone: the address is the project's, and a `variant=` written there
 * would be read by the package as the project's own.
 */
export function useRememberedLayout(resourceId: string): void {
  const { view, viewVariant } = useCurrentViewResourceContext()
  const first = view?.layouts?.[0]?.id
  React.useEffect(() => {
    if (viewVariant) layouts.set(resourceId, viewVariant === first ? "" : viewVariant)
  }, [resourceId, viewVariant, first])
}
