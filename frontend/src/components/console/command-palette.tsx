import * as React from "react"
import {
  BookOpen,
  CalendarClock,
  FolderGit2,
  FolderPlus,
  ListChecks,
  LayoutGrid,
  Lightbulb,
  MessageCircle,
  MessageSquarePlus,
  MessagesSquare,
  Plus,
  RefreshCw,
  Scale,
  Settings2,
  Target,
} from "lucide-react"
import { ActionList } from "react-data-form"
import { generateLinkByResource, useNavigate } from "react-resource-view"

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command"
import { useConsole } from "@/hooks/use-console"
import { hotkeyLabel, useHotkeys } from "@/hooks/use-hotkeys"
import { titleOf, useBoard } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { useRoute } from "@/lib/router"
import {
  PROJECTS,
  idOf,
  newProjectHref,
  projectHref,
  projectsHref,
  projectsOnce,
  useProjects,
} from "@/resources/projects"
import { goalsHref, newGoalHref } from "@/resources/goals"
import { ideasHref, newIdeaHref } from "@/resources/ideas"
import { newScheduleHref, schedulesHref } from "@/resources/schedules"
import { sessionsHref } from "@/resources/sessions"
import { settingsHref } from "@/resources/settings"
import { boardHref, ticketHref, tickets } from "@/resources/tickets"

import { CONTEXT_ANCHOR } from "./context-block"
import { useOpenSeries } from "./ticket-decision"
import { openTalk, toggleTalk } from "@/lib/talk"

/* Ctrl+K: everywhere the console can take you, typed rather than clicked.
 *
 * What it lists is what the console already has — its pages, the projects, the
 * tickets on the board — and the few things done from anywhere: whatever the
 * console creates (a ticket — for the project whose page is open, on one —, a
 * project, an idea, a goal, a schedule, a session), the conversation, a
 * resynchronisation, the series of blocked tickets or of those in review.
 * Nothing in it is a page of its own; an entry is a link the menu or a card
 * already offers, found by its name.
 *
 * N, out of a field, is "New ticket" without the palette: listened for here,
 * where the entry it stands for is, so the project it starts with is the same.
 *
 * The pages are said again here rather than read off the scope's menu, icons
 * and all: the scope imports the bar this palette's button sits in, and
 * reading it from here would be a circle.
 */

const OPENED = "ponos:palette"

/** Open the palette, from anywhere on the page — the button in the bar. */
export const openPalette = () => window.dispatchEvent(new Event(OPENED))

const PAGES = [
  { name: "Dashboard", icon: LayoutGrid, href: boardHref },
  { name: "Projects", icon: FolderGit2, href: projectsHref },
  { name: "Schedules", icon: CalendarClock, href: schedulesHref },
  { name: "Ideas", icon: Lightbulb, href: ideasHref },
  { name: "Goals", icon: Target, href: goalsHref },
  { name: "Sessions", icon: MessagesSquare, href: sessionsHref },
  { name: "Global context", icon: BookOpen, href: () => `${projectsHref()}#${CONTEXT_ANCHOR}` },
  { name: "Settings", icon: Settings2, href: () => settingsHref() },
]

export function CommandPalette() {
  const t = useT()
  const navigate = useNavigate()
  const board = useBoard()
  const listed = useProjects()
  const { refresh, resetChat } = useConsole()
  const { params } = useRoute()
  // The project whose page is open, if one is: a new ticket starts with it.
  // Only one with a page of its own can be a ticket's.
  const here =
    params.resourceId === PROJECTS && params.id
      ? listed?.projects.find((project) => idOf(project) === params.id && project.id)
      : undefined
  const openSeries = useOpenSeries()
  const blocked = board.tickets.filter((ticket) => ticket.column === "blocked").length
  const review = board.tickets.filter((ticket) => ticket.column === "review").length
  const [open, setOpen] = React.useState(false)
  // What had the focus before the palette opened, and gets it back: the
  // dialog has no trigger to hand it to.
  const before = React.useRef<HTMLElement | null>(null)
  // What an entry asked for, done once the palette has let go of the focus —
  // so the drawer it opens takes the focus rather than losing it to the page.
  const pending = React.useRef<(() => void) | null>(null)

  const change = React.useCallback((next: boolean) => {
    if (next) {
      before.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      pending.current = null
    }
    setOpen(next)
  }, [])

  React.useEffect(() => {
    const listener = () => change(true)
    window.addEventListener(OPENED, listener)
    return () => window.removeEventListener(OPENED, listener)
  }, [change])

  const newTicketHref = () =>
    generateLinkByResource({
      resource: tickets,
      resourceAction: ActionList.create,
      defaultData: here ? { project: here.id } : undefined,
    })

  useHotkeys({
    palette: () => change(!open),
    // Under a window — a form half written, a picker typed into — the key is
    // the window's. The palette is one: there it is a letter in its field.
    newTicket: () => {
      if (document.querySelector('[role="dialog"]')) return false
      void navigate({ to: newTicketHref() })
    },
  })

  // The projects are read by their own page; one opened straight on the board
  // has not read them yet.
  React.useEffect(() => {
    if (open) void projectsOnce().catch(() => undefined)
  }, [open])

  const run = (action: () => void) => {
    pending.current = action
    setOpen(false)
  }
  const go = (href: string) => run(() => void navigate({ to: href }))

  const drawerKey = hotkeyLabel("console")
  const ticketKey = hotkeyLabel("newTicket")
  const newTicket = here ? t("New ticket for {{project}}", { project: here.name }) : t("New ticket")

  return (
    <CommandDialog
      open={open}
      onOpenChange={change}
      title={t("Command palette")}
      description={t("Find a page, a project or a ticket, or run an action.")}
      closeLabel={t("Close")}
      className="top-[20%] translate-y-0 sm:max-w-xl"
      onCloseAutoFocus={(event) => {
        event.preventDefault()
        const back = before.current
        before.current = null
        if (back?.isConnected) back.focus()
        const action = pending.current
        pending.current = null
        action?.()
      }}
    >
      <CommandInput placeholder={t("Type a page, a project, a ticket…")} />
      <CommandList className="max-h-[min(60vh,420px)]">
        <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>

        <CommandGroup heading={t("Actions")}>
          <CommandItem
            value={t("Open or close the console")}
            keywords={["console", "chat", "discussion"]}
            onSelect={() => run(toggleTalk)}
          >
            <MessageCircle />
            {t("Open or close the console")}
            <CommandShortcut>{drawerKey.label}</CommandShortcut>
          </CommandItem>
          <CommandItem value={newTicket} keywords={["create", "ticket"]} onSelect={() => go(newTicketHref())}>
            <Plus />
            <span className="truncate">{newTicket}</span>
            <CommandShortcut>{ticketKey.label}</CommandShortcut>
          </CommandItem>
          <CommandItem
            value={t("New project")}
            keywords={["create", "project"]}
            onSelect={() => go(newProjectHref())}
          >
            <FolderPlus />
            {t("New project")}
          </CommandItem>
          <CommandItem value={t("New idea")} keywords={["create", "idea"]} onSelect={() => go(newIdeaHref())}>
            <Lightbulb />
            {t("New idea")}
          </CommandItem>
          <CommandItem value={t("New goal")} keywords={["create", "goal"]} onSelect={() => go(newGoalHref())}>
            <Target />
            {t("New goal")}
          </CommandItem>
          <CommandItem
            value={t("New schedule")}
            keywords={["create", "schedule", "recurring"]}
            onSelect={() => go(newScheduleHref())}
          >
            <CalendarClock />
            {t("New schedule")}
          </CommandItem>
          {/* As the Sessions page starts one: a fresh conversation, in the drawer. */}
          <CommandItem
            value={t("New session")}
            keywords={["create", "session", "conversation", "chat"]}
            onSelect={() =>
              run(() => {
                void resetChat()
                openTalk()
              })
            }
          >
            <MessageSquarePlus />
            {t("New session")}
          </CommandItem>
          <CommandItem
            value={t("Resynchronise now")}
            keywords={["refresh", "sync"]}
            onSelect={() => run(() => void refresh())}
          >
            <RefreshCw />
            {t("Resynchronise now")}
          </CommandItem>
          {/* The columns waiting on you, gone through one ticket after another — see `ticket-series.tsx`. */}
          {blocked ? (
            <CommandItem
              value={t("Unblock the tickets")}
              keywords={["unblock", "blocked", "series"]}
              onSelect={() => run(() => openSeries("blocked"))}
            >
              <ListChecks />
              {t("Unblock the tickets")}
              <CommandShortcut className="tracking-normal">{blocked}</CommandShortcut>
            </CommandItem>
          ) : null}
          {review ? (
            <CommandItem
              value={t("Decide on the tickets in review")}
              keywords={["decide", "review", "series"]}
              onSelect={() => run(() => openSeries("review"))}
            >
              <Scale />
              {t("Decide on the tickets in review")}
              <CommandShortcut className="tracking-normal">{review}</CommandShortcut>
            </CommandItem>
          ) : null}
        </CommandGroup>

        <CommandSeparator />
        <CommandGroup heading={t("Pages")}>
          {PAGES.map(({ name, icon: Icon, href }) => (
            <CommandItem
              key={name}
              value={t(name)}
              keywords={[name, "page"]}
              onSelect={() => go(href())}
            >
              <Icon />
              {t(name)}
            </CommandItem>
          ))}
        </CommandGroup>

        {listed?.projects.length ? (
          <>
            <CommandSeparator />
            <CommandGroup heading={t("Projects")}>
              {listed.projects.map((project) => (
                <CommandItem
                  key={idOf(project)}
                  value={`${project.name} ${idOf(project)}`}
                  keywords={["project"]}
                  onSelect={() => go(projectHref(idOf(project)))}
                >
                  <FolderGit2 />
                  {project.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}

        {board.tickets.length ? (
          <>
            <CommandSeparator />
            <CommandGroup heading={t("Tickets")}>
              {board.tickets.map((ticket) => (
                <CommandItem
                  key={ticket.id}
                  value={`${titleOf(ticket)} ${ticket.short} ${ticket.id}`}
                  keywords={["ticket", ticket.project]}
                  onSelect={() => go(ticketHref(ticket.id))}
                >
                  <LayoutGrid />
                  <span className="truncate">{titleOf(ticket)}</span>
                  <CommandShortcut className="tracking-normal">#{ticket.short}</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
    </CommandDialog>
  )
}
