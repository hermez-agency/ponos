import * as React from "react"
import { Bell, Cpu, FolderGit2, GitPullRequest, Inbox, Play, Plug, Settings2, SlidersHorizontal } from "lucide-react"
import { ActionList } from "react-data-form"
import {
  createViewResource,
  generateLink,
  type IconType,
  type TabDefinition,
} from "react-resource-view"

import { api } from "@/lib/api"
import { SCOPE } from "@/lib/resource-view"
import { currentSettings, publishSettings } from "@/lib/settings-store"
import type { SettingGroup, Settings } from "@/lib/types"

/* The configuration, declared once for react-resource-view.
 *
 * `config.toml` is one thing, so it is one record: the page is the `read` view
 * of a resource with a single item, and each of its six groups, the GitHub page and the MCP page, is a sub-page
 * of it — the tab you are on carried in the address, so a link to the
 * notification settings is a link you can send somebody.
 *
 * Six rather than one per table of the file: the file is organised the way the
 * loader reads it, the page the way somebody looks for a setting. A tab draws
 * the group you are looking at and nothing else; what you type on a page you
 * leave is kept in the store and given back when you come to it again.
 *
 * The tabs are built from what the server says the file holds — a group the
 * runner gains is a sub-page the day it is described — which is why the list
 * is read from the store rather than written down here. See `settings-store`.
 */

export const SETTINGS = "settings"

/** The file is the record, and there is only ever the one. */
const THE_FILE = "config"

/** The configuration as the views hold it: the description, and an identity. */
export interface SettingsItem extends Settings {
  "@id": string
  "@type": string
  id: string
  /** What the bar's breadcrumb calls it, which would otherwise be "#config". */
  name: string
}

/* What each page is, at a glance. Decoration rather than a second list of
 * groups: a key nobody has drawn an icon for gets the page's own. */
const ICONS: Record<string, IconType> = {
  general: SlidersHorizontal,
  source: Inbox,
  execution: Play,
  models: Cpu,
  code: FolderGit2,
  communication: Bell,
  mcp: Plug,
  "github-app": GitPullRequest,
}

/* The one page the file does not describe: the MCP tab is about the console
 * and Claude Code, not about a key of `config.toml`, so it is added here after
 * the server's groups rather than described by them. */
const MCP_TAB = "mcp"

/* The GitHub tab, for the same reason: the app Ponos works GitHub through is
 * kept with the secrets, not in a key of the file. */
const GITHUB_TAB = "github-app"

const LazyGithubPage = React.lazy(() =>
  import("@/components/console/github-page").then((module) => ({ default: module.GithubPage }))
)

const GithubPage = () => (
  <React.Suspense fallback={null}>
    <LazyGithubPage />
  </React.Suspense>
)

/* The MCP tab: a page opened now and then, kept out of the first load, which has a budget. */
const LazyMcpPage = React.lazy(() =>
  import("@/components/console/mcp-page").then((module) => ({ default: module.McpPage }))
)

const McpPage = () => (
  <React.Suspense fallback={null}>
    <LazyMcpPage />
  </React.Suspense>
)

const LazyGroupPage = React.lazy(() =>
  import("@/components/console/settings-page").then((module) => ({ default: module.GroupPage }))
)

/* One component per page rather than one built as the tabs are drawn: a
 * component born in a render is a component React remounts on the next one. */
const PAGES = new Map<string, React.FC>()

function pageFor(group: SettingGroup): React.FC {
  const known = PAGES.get(group.key)
  if (known) return known
  const page = () => (
    <React.Suspense fallback={null}>
      <LazyGroupPage group={group.key} />
    </React.Suspense>
  )
  PAGES.set(group.key, page)
  return page
}

/* The tabs, as the description last read says them.
 *
 * Built from what the server says the file holds — never from a list kept
 * here — so they are only known once the configuration is read. And
 * react-resource-view 1.0 reads a declaration's tabs once, as the resource is
 * declared, keeping the array it is handed: so it is handed this one, filled
 * again each time the configuration is read, before the page that draws the
 * tabs is drawn.
 */
const TABS: TabDefinition<SettingsItem>[] = []

function tellTheTabs() {
  const pages: TabDefinition<SettingsItem>[] = (currentSettings()?.groups ?? []).map((group) => ({
    id: group.key,
    // Drawn by the package, which translates both as it draws.
    label: group.title,
    description: group.blurb,
    icon: ICONS[group.key] ?? Settings2,
    component: pageFor(group),
  }))
  if (pages.length)
    pages.push({
      id: GITHUB_TAB,
      label: "GitHub",
      description: "The GitHub App tickets clone, push and open their pull requests with.",
      icon: ICONS[GITHUB_TAB],
      component: GithubPage,
    })
  if (pages.length)
    pages.push({
      id: MCP_TAB,
      label: "MCP",
      description: "What an MCP is, how to plug Ponos into Claude, and the ones the sessions use.",
      icon: ICONS[MCP_TAB],
      component: McpPage,
    })
  TABS.splice(0, TABS.length, ...pages)
}

/* -- the head of the page ---------------------------------------------------- */

/* Where you are, how to find a setting, and whatever `doctor` would refuse to
 * start over: drawn with the page, and fetched with it rather than with the
 * console, whose first load has a budget. */
const Head = React.lazy(() =>
  import("@/components/console/settings-head").then((module) => ({ default: module.SettingsHead }))
)

const SettingsHead = () => (
  <React.Suspense fallback={null}>
    <Head />
  </React.Suspense>
)

/* The layout's header, in place of the package's: nothing. The page says what it
 * is in `SettingsHead`, and the bar above it already says where you are. */
const NoHeader = () => null

export const settings = createViewResource<SettingsItem>(SETTINGS, {
  name: "Settings",
  path: "/api/settings",
  icon: Settings2,
  // The one page, and nothing to write or delete through the package. Its list
  // is allowed only to be linked to — the breadcrumb does — and leads to the
  // page (see `App`).
  permissions: ["list", "read"],
  repository: {
    getCollection: async () => {
      throw new Error("there is one configuration; it is not listed")
    },
    getItem: async () => {
      const drawn = await api.settings()
      // Published before it is returned: the tabs are built from the store, and
      // they are drawn the moment this resolves.
      publishSettings(drawn)
      tellTheTabs()
      return {
        data: { ...drawn, id: THE_FILE, name: "config.toml", "@id": "/api/settings", "@type": SETTINGS },
      }
    },
    createItem: async () => {
      throw new Error("the configuration is not created from the console")
    },
    updateItem: async () => {
      throw new Error("a page saves itself; see settings-bits")
    },
    removeItem: async () => {
      throw new Error("the configuration is not deleted from the console")
    },
  },
  views: {
    read: {
      // The dashboard's width and margins, like every page of the menu.
      fullWidth: true,
      components: {
        view: SettingsHead,
        // No header from the layout: it said the page twice over `SettingsHead`
        // — a way back, "Settings", "#config" — and its way back led to a list
        // the one file does not have.
        navigation: NoHeader,
      },
      tabs: {
        // Six pages read as a short column beside the fields; on a phone the
        // package lays them out as a row that scrolls.
        orientation: "vertical",
        items: TABS,
      },
    },
  },
})

/** Where the settings are — one page of them, or the page a card is on. */
export const settingsHref = (page?: string) =>
  generateLink({
    scope: SCOPE,
    resourceId: SETTINGS,
    resourceAction: ActionList.read,
    id: THE_FILE,
    subResource: page,
  })
