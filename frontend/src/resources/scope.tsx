import { ActionList } from "react-data-form"
import {
  createAdminLayout,
  type MenuItemInterface,
  type ScopeConfig,
  type ScopeInterface,
} from "react-resource-view"

import { BoardCount, Mark, SidebarFooter, TopBarEnd } from "@/components/console/shell"
import { t } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"

import { goals, goalsHref } from "./goals"
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
 * time somebody picks the table. The package keeps the getters as it loads the
 * scope, and reads them every time it draws the menu.
 */

/* A phone's bar holds five entries at 360px, More included, and a label cut in
 * two is worse than a page one tap further away: the bar's entries are the
 * four a phone reaches for, and the two behind More are the same pages in the
 * menu's order. The sidebar is never drawn on a phone, so what is hidden there
 * is only out of the bar; the footer's copy of the two is hidden on a desktop,
 * where the sidebar has them already. */
const phone = () => window.matchMedia("(width < 48rem)").matches

const entry = (
  icon: MenuItemInterface["icon"],
  name: string,
  href: () => string,
  badge?: MenuItemInterface["badge"],
  hidden?: () => boolean
): MenuItemInterface => ({
  icon,
  badge,
  get hidden() {
    return hidden?.()
  },
  get name() {
    return t(name)
  },
  get href() {
    return href()
  },
})

/* The pages you go to every day, down the left — and along the bottom of a
 * phone, where four of them and More are what fits a 360px screen. */
const MENU: MenuItemInterface[] = [
  entry(tickets.icon, "Dashboard", boardHref, BoardCount),
  entry(projects.icon, "Projects", projectsHref),
  // No count, here as under Projects: the only way to know is to ask the
  // board, and this menu is redrawn every time the board moves.
  entry(schedules.icon, "Schedules", schedulesHref, undefined, phone),
  entry(ideas.icon, "Ideas", ideasHref),
  entry(goals.icon, "Goals", goalsHref, undefined, phone),
  entry(sessions.icon, "Sessions", sessionsHref),
]

/* The rest, pinned at the foot of the sidebar, over its version and its
 * buttons; on a phone the layout lists them behind the bar's last entry, More,
 * with the same version and buttons under them. Schedules and Goals are the
 * two that a phone reaches from there rather than from the bar. */
const FOOTER_MENU: MenuItemInterface[] = [
  entry(schedules.icon, "Schedules", schedulesHref, undefined, () => !phone()),
  entry(goals.icon, "Goals", goalsHref, undefined, () => !phone()),
  entry(settings.icon, "Settings", () => settingsHref()),
]

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
    goals,
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
