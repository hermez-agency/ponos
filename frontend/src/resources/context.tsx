import * as React from "react"
import { BookOpen, Brain, KeyRound, Library, NotebookText } from "lucide-react"
import { ActionList } from "react-data-form"
import {
  createViewResource,
  generateLink,
  type IconType,
  type TabDefinition,
} from "react-resource-view"

import { SCOPE } from "@/lib/resource-view"
import { isAdmin } from "@/lib/role"

/* Everything a session is given besides its ticket, declared once for
 * react-resource-view.
 *
 * Like the settings, the page is the `read` view of a resource with a single
 * item, and each thing a session is given is a tab of it — the tab you are on
 * carried in the address (`console/context/read/context/<tab>`), so a link to
 * the vault is a link you can send somebody. The tabs are heavy and opened now
 * and then, so each is fetched on demand: the first load has a budget.
 *
 * A tab is one entry of `TAB_DEFINITIONS`: Skills, Memory and the Library
 * arrive as entries of that list, without touching the ones already there.
 */

export const CONTEXT = "context"

/** The page is the record, and there is only ever the one. */
const THE_PAGE = "context"

/** The tab the page opens on, and the one an address naming none means. */
export const STANDING_TAB = "standing"
export const VAULT_TAB = "vault"
export const MEMORY_TAB = "memory"
export const LIBRARY_TAB = "library"

/** The page as the views hold it: only what the bar's breadcrumb needs. */
export interface ContextItem {
  "@id": string
  "@type": string
  id: string
  name: string
}

const lazyTab = (load: () => Promise<{ default: React.ComponentType }>): React.FC => {
  const Lazy = React.lazy(load)
  return () => (
    <React.Suspense fallback={null}>
      <Lazy />
    </React.Suspense>
  )
}

const StandingContext = lazyTab(() =>
  import("@/components/console/context-block").then((module) => ({ default: module.ContextBlock }))
)

const Vault = lazyTab(() =>
  import("@/components/console/vault-page").then((module) => ({ default: module.VaultPage }))
)

const Memory = lazyTab(() =>
  import("@/components/console/memory-page").then((module) => ({ default: module.MemoryPage }))
)

const LibraryTab = lazyTab(() =>
  import("@/components/console/library-page").then((module) => ({ default: module.LibraryPage }))
)

interface ContextTab {
  tab: Omit<TabDefinition<ContextItem>, "icon"> & { icon: IconType }
  /** Whether this role is given the tab at all; the API refuses the rest. */
  allowed?: () => boolean
}

const TAB_DEFINITIONS: ContextTab[] = [
  {
    tab: {
      id: STANDING_TAB,
      label: "Context",
      description: "What every ticket is told, for all the projects.",
      icon: NotebookText,
      component: StandingContext,
    },
  },
  {
    tab: {
      id: MEMORY_TAB,
      label: "Memory",
      description: "What Ponos remembers from one session to the next, for all the projects or one.",
      icon: Brain,
      component: Memory,
    },
  },
  {
    tab: {
      id: LIBRARY_TAB,
      label: "Library",
      description: "Reference files kept for the sessions, for all the projects or some.",
      icon: Library,
      component: LibraryTab,
    },
  },
  {
    // The keys a session is given: an admin's, and not even listed to anybody else.
    allowed: isAdmin,
    tab: {
      id: VAULT_TAB,
      label: "Vault",
      description: "The logins, passwords and API keys the sessions are given, kept encrypted.",
      icon: KeyRound,
      component: Vault,
    },
  },
]

/* The array the package keeps as the resource is declared: filled again each
 * time the page is read, once the role is known. */
const TABS: TabDefinition<ContextItem>[] = []

function tellTheTabs() {
  TABS.splice(0, TABS.length, ...TAB_DEFINITIONS.filter(({ allowed }) => !allowed || allowed()).map(({ tab }) => tab))
}

/* The page's head, fetched with it; and no header from the layout, which would
 * say the page twice over it. */
const Head = React.lazy(() =>
  import("@/components/console/context-head").then((module) => ({ default: module.ContextHead }))
)

const ContextHead = () => (
  <React.Suspense fallback={null}>
    <Head />
  </React.Suspense>
)

const NoHeader = () => null

export const context = createViewResource<ContextItem>(CONTEXT, {
  name: "Context",
  path: "/api/context-page",
  icon: BookOpen,
  // One page, nothing to write or delete through the package; its list is only
  // linked to — the breadcrumb does — and leads to the page (see `App`).
  permissions: ["list", "read"],
  repository: {
    getCollection: async () => {
      throw new Error("there is one context page; it is not listed")
    },
    getItem: async () => {
      tellTheTabs()
      return { data: { id: THE_PAGE, name: "Context", "@id": "/api/context-page", "@type": CONTEXT } }
    },
    createItem: async () => {
      throw new Error("the context page is not created")
    },
    updateItem: async () => {
      throw new Error("a tab saves itself")
    },
    removeItem: async () => {
      throw new Error("the context page is not deleted")
    },
  },
  views: {
    read: {
      fullWidth: true,
      components: { view: ContextHead, navigation: NoHeader },
      tabs: { orientation: "vertical", items: TABS },
    },
  },
})

/** Where the context is — the page, or one of its tabs. */
export const contextHref = (tab?: string) =>
  generateLink({
    scope: SCOPE,
    resourceId: CONTEXT,
    resourceAction: ActionList.read,
    id: THE_PAGE,
    subResource: tab,
  })
