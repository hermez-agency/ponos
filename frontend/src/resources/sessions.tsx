import * as React from "react"
import { MessagesSquare } from "lucide-react"
import { ActionList } from "react-data-form"
import { createViewResource, generateLink } from "react-resource-view"

import { SCOPE } from "@/lib/resource-view"

/* The conversations, as a page of the menu.
 *
 * Declared as a list, as the projects and the ideas are, so the bar names it
 * as it names them — "Ponos › Sessions", not the resource and then the one
 * record it used to be read as. But the package lists nothing: the list of
 * sessions is drawn by the page itself, from its own endpoint, with its search,
 * and the header with it (see `SessionsPage`). */

export const SESSIONS = "sessions"

/* A page opened now and then, kept out of the first load, which has a budget. */
const SessionsPage = React.lazy(() =>
  import("@/components/console/sessions-page").then((module) => ({ default: module.SessionsPage }))
)

const LazySessions = () => (
  <React.Suspense fallback={null}>
    <SessionsPage />
  </React.Suspense>
)

interface SessionsItem {
  "@id": string
  "@type": string
  id: string
}

/* A session is started, renamed and deleted from the page, never as a record. */
const refused = async (): Promise<never> => {
  throw new Error("the sessions are managed from their page")
}

export const sessions = createViewResource<SessionsItem>(SESSIONS, {
  name: "Sessions",
  path: "/api/chat/sessions",
  icon: MessagesSquare,
  // The page, and nothing to read, write or delete through the package.
  permissions: ["list"],
  repository: {
    getItem: refused,
    getCollection: refused,
    createItem: refused,
    updateItem: refused,
    removeItem: refused,
  },
  views: {
    list: {
      // The projects' width, like every list: the page is drawn by `SessionsPage`.
      fullWidth: true,
      components: { view: LazySessions },
    },
  },
})

/** Where the sessions are. */
export const sessionsHref = () =>
  generateLink({
    scope: SCOPE,
    resourceId: SESSIONS,
    resourceAction: ActionList.list,
  })
