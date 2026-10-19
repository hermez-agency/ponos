import * as React from "react"
import { RouterProvider } from "@tanstack/react-router"
import { ActionList } from "react-data-form"
import {
  Navigate,
  ScopeProvider,
  ViewResourceContextProvider,
  findResource,
  useResolvedViewParams,
  useScopeContext,
  type ViewResourceContextParams,
} from "react-resource-view"

import { CONTEXT_ANCHOR } from "@/components/console/context-block"
import { UpdateNotice } from "@/components/console/install-app"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ConsoleProvider, useConsole } from "@/hooks/use-console"
import { RunnerMoodProvider } from "@/hooks/use-mood"
import { useBoard } from "@/lib/board-store"
import { useLanguage, useT } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"
import { consoleRouter, useRoute } from "@/lib/router"
import { keepTheMenuLive, menuName, scopes } from "@/resources/scope"
import { projectsHref } from "@/resources/projects"
import { SESSIONS, sessionsHref } from "@/resources/sessions"
import { SETTINGS, settingsHref } from "@/resources/settings"
import { TICKETS, boardHref } from "@/resources/tickets"

/* The shape of the page.
 *
 * react-resource-view's admin layout: a menu down the left built from the
 * scope, a bar over the page, a bottom navigation on a phone. Every page is a
 * resource of that scope — the board, a ticket, the projects, the
 * schedules, the settings — so what the address names is handed to the
 * package, which draws the matching view inside the layout the scope declares.
 *
 * One thing stays outside it: the conversation, a drawer opened by the bubble
 * in the bottom corner at every width. The page keeps its width until you ask
 * for it, and a trip through the menu does not close it.
 */

const ACTIONS = new Set<string>(Object.values(ActionList))

/** The page the address names, drawn in the scope's layout. */
function Page({ params }: { params: ViewResourceContextParams }) {
  const language = useLanguage()
  const scope = useScopeContext()?.scope
  keepTheMenuLive(scope)
  const action =
    params.resourceAction && ACTIONS.has(params.resourceAction)
      ? params.resourceAction
      : ActionList.list
  const resourceId = params.resourceId ?? TICKETS
  const resource = findResource({ scope: SCOPE, resourceId })
  const resolved = useResolvedViewParams({ ...params, resource, resourceAction: action })
  // An address naming a page this console does not have lands on the board,
  // rather than on an error thrown from inside the package — the live page's
  // `/?view=console/live/list` among them, now that sessions are read on their
  // tickets, and the statistics' `/?view=console/statistics/list`, now that
  // they are drawn at the top of the dashboard.
  // The context was a page of its own, and is the first block of the projects
  // now: a bookmarked `/?view=console/context/list` leads there.
  if (!resource && resourceId === "context")
    return <Navigate to={`${projectsHref()}#${CONTEXT_ANCHOR}`} replace />
  if (!resource) return <Navigate to={boardHref()} replace />
  // The settings are one file, so they have no list: the package still links
  // to one — the breadcrumb in the bar does — and a list asked for is the file.
  if (resourceId === SETTINGS && action === ActionList.list)
    return <Navigate to={settingsHref()} replace />
  // The sessions the other way round: a list now, whose page draws it, and
  // the one record they used to be read as is a bookmarked address that leads
  // there.
  if (resourceId === SESSIONS && action !== ActionList.list)
    return <Navigate to={sessionsHref()} replace />
  return (
    // The language is part of the key: what the package draws — the view's
    // name, a column header, the words on a form — it reads from the
    // dictionary as it builds, not as it renders. The resource, the action and
    // the id are in it too, because the context resolves them once.
    <ViewResourceContextProvider
      key={`${language}:${resourceId}:${action}:${String(resolved.id ?? "")}`}
      decoratorComponent={scope?.decoratorComponent}
      {...resolved}
    />
  )
}

/** What the tab says: where you are, so seven tabs of "Ponos" are not a row to open one by one. */
function useTitle(params: ViewResourceContextParams, ticketShort?: string) {
  const t = useT()
  const resourceId = String(params.resourceId ?? TICKETS)
  const here =
    resourceId === TICKETS && params.resourceAction === ActionList.read && params.id
      ? `#${ticketShort ?? String(params.id).slice(-8)}`
      : (menuName(resourceId) ?? t("Dashboard"))
  React.useEffect(() => {
    document.title = here ? `${here} · Ponos` : "Ponos"
  }, [here])
}

/* The address says which ticket is open — its page, or the window over a list,
 * which the address names under that list; the board says what it is, so the
 * discussion loads while the page is still being read.
 *
 * A component of its own, drawing nothing: opening a ticket changes the
 * console's `ticket`, and a `Console` that read it drew the whole page again —
 * every card of the board — on opening, on closing and when the stream moved
 * the board. Here only this is drawn again. */
const ticketOf = (opened?: ViewResourceContextParams): string | null =>
  opened &&
  (opened.resourceId ?? TICKETS) === TICKETS &&
  opened.resourceAction === ActionList.read &&
  opened.id
    ? String(opened.id)
    : null

function OpenTicket({ params }: { params: ViewResourceContextParams }) {
  const board = useBoard()
  const { ticket, openTicket, closeTicket } = useConsole()

  const ticketId = ticketOf(params) ?? ticketOf(params.childViewResource)
  React.useEffect(() => {
    if (!ticketId) {
      closeTicket()
      return
    }
    const known = board.tickets.find((item) => item.id === ticketId)
    if (known) openTicket(known)
  }, [ticketId, board, openTicket, closeTicket])

  useTitle(params, ticket?.short)
  return null
}

/* Both wait for a key or a button, so neither is in the first load, which has a
 * budget: they are fetched once the page is up. */
const TalkDrawer = React.lazy(() =>
  import("@/components/console/talk-drawer").then((module) => ({ default: module.TalkDrawer }))
)
const CommandPalette = React.lazy(() =>
  import("@/components/console/command-palette").then((module) => ({ default: module.CommandPalette }))
)

function Console() {
  const { params, moved } = useRoute()

  if (moved) return <Navigate to={moved} replace />

  return (
    <>
      <OpenTicket params={params} />
      <React.Suspense fallback={null}>
        <ScopeProvider scopeName={SCOPE} configScope={scopes}>
          <Page params={params} />
        </ScopeProvider>
      </React.Suspense>

      {/* Over everything, at every width: the conversation is never a page you
          navigate to and lose your place for. */}
      <React.Suspense fallback={null}>
        <TalkDrawer />
        {/* Ctrl+K, from every page: inside the router, which its links go through. */}
        <CommandPalette />
      </React.Suspense>
    </>
  )
}

const router = consoleRouter(Console)

export default function App() {
  return (
    <TooltipProvider>
      <ConsoleProvider>
        <RunnerMoodProvider>
          <RouterProvider router={router} />
          <Toaster />
          <UpdateNotice />
        </RunnerMoodProvider>
      </ConsoleProvider>
    </TooltipProvider>
  )
}
