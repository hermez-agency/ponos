import { ActionList } from "react-data-form"
import {
  createAdminLayout,
  type MenuItemInterface,
  type ResolvedScope,
  type ScopeConfig,
  type ScopeInterface,
} from "react-resource-view"

import { BoardEntry, Mark, SidebarFooter, TopBarEnd } from "@/components/console/shell"
import { t } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"

import { ideas, ideasHref, scopedIdeas } from "./ideas"
import { pairResources } from "./pairs"
import { projects, projectsHref } from "./projects"
import { schedules, schedulesHref } from "./schedules"
import { sessions, sessionsHref } from "./sessions"
import { settings, settingsHref } from "./settings"
import { TICKETS, boardHref, projectTickets, tickets } from "./tickets"

/* The console, as one scope of react-resource-view.
 *
 * A scope is what the package's admin layout is built from: its resources, the
 * menu down the left, the frame every page is drawn in, and the page an
 * address that names nothing opens on. So this is the whole of the console's
 * shape in one declaration — the pages themselves are the resources.
 *
 * The names and the links are getters. A name is read from the dictionary as
 * the menu is drawn, so the language can change after this is declared; the
 * board's link carries the layout it was last worked in, which changes every
 * time somebody picks the table.
 */

const entry = (
  icon: MenuItemInterface["icon"],
  name: string,
  href: () => string,
  component?: MenuItemInterface["component"]
): MenuItemInterface => ({
  icon,
  component,
  get name() {
    return t(name)
  },
  get href() {
    return href()
  },
})

/* The pages you go to every day, down the left — and along the bottom of a
 * phone, where three of them and More are what fits a 360px screen. */
const MENU: MenuItemInterface[] = [
  entry(tickets.icon, "Dashboard", boardHref, BoardEntry),
  entry(projects.icon, "Projects", projectsHref),
  // No count, here as under Projects: the only way to know is to ask the
  // board, and this menu is redrawn every time the board moves.
  entry(schedules.icon, "Schedules", schedulesHref),
]

/* The rest, pinned at the foot of the sidebar, over its version and its
 * buttons; on a phone the layout lists them behind the bar's last entry, More,
 * with the same version and buttons under them. */
const FOOTER_MENU: MenuItemInterface[] = [
  entry(ideas.icon, "Ideas", ideasHref),
  entry(sessions.icon, "Sessions", sessionsHref),
  entry(settings.icon, "Settings", () => settingsHref()),
]

/* The menu the layout draws is a copy: react-resource-view 1.1 resolves a
 * scope as it loads it, once, and spreads every entry into a new object — so
 * a getter is read there, and the menu would say its names in the language
 * the console opened in, and link the board in the layout it opened on. The
 * getters are put back on the copy, entry by entry: the copy is in the menu's
 * order. The package keeps them itself from the release of
 * hermez-agency/react-resource-view#136, and this goes with it. The
 * links pinned at the foot are not copied: they are these objects. */
const live = new WeakSet<object>()

export function keepTheMenuLive(scope: ResolvedScope | undefined) {
  if (!scope?.menu || live.has(scope)) return
  live.add(scope)
  scope.menu.forEach((copy, index) => {
    const original = MENU[index]
    if (!original) return
    for (const [key, said] of Object.entries(Object.getOwnPropertyDescriptors(original)))
      if (said.get) Object.defineProperty(copy, key, said)
  })
}

export const consoleScope: ScopeInterface = {
  name: SCOPE,
  label: "Ponos",
  // Every resource of the console, the lists drawn inside another page
  // included: a scope is what a resource's links are written under.
  resources: [
    tickets,
    projects,
    schedules,
    ideas,
    sessions,
    settings,
    projectTickets,
    scopedIdeas,
    ...Object.values(pairResources),
  ],
  decoratorComponent: createAdminLayout({
    logo: <Mark />,
    topBarEnd: <TopBarEnd />,
    sidebarFooter: <SidebarFooter />,
    footerMenu: FOOTER_MENU,
  }),
  menu: MENU,
  // An address that names nothing is the board.
  defaultViewResourceContextParams: {
    scope: SCOPE,
    resourceId: TICKETS,
    resourceAction: ActionList.list,
  },
}

/** What `ScopeProvider` loads the scope from: there is one, and it is already here. */
export const scopes: ScopeConfig = { [SCOPE]: async () => consoleScope }
