import * as React from "react"
import {
  BookOpen,
  CalendarClock,
  FolderGit2,
  FolderPlus,
  FilePen,
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
  Stethoscope,
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
import { OPENED } from "@/lib/palette"
import { says, ticketsFor } from "@/lib/palette-search"
import { useRoute } from "@/lib/router"
import { terms } from "@/lib/ticket-search"
import {
  CONTEXT_ANCHOR,
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

import { useOpenSeries } from "./ticket-decision"
import { openTalk, toggleTalk } from "@/lib/talk"
import { canAct } from "@/lib/role"

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

const PAGES = [
  { name: "Dashboard", icon: LayoutGrid, href: boardHref },
  { name: "Projects", icon: FolderGit2, href: projectsHref },
  { name: "Schedules", icon: CalendarClock, href: schedulesHref },
  { name: "Ideas", icon: Lightbulb, href: ideasHref },
  { name: "Goals", icon: Target, href: goalsHref },
  { name: "Conversations", icon: MessagesSquare, href: sessionsHref },
  { name: "Global context", icon: BookOpen, href: () => `${projectsHref()}#${CONTEXT_ANCHOR}` },
  { name: "Settings", icon: Settings2, href: () => settingsHref() },
]

/** An entry of the Actions group: what it says, what else finds it, and what it does. */
interface Action {
  value: string
  keywords: string[]
  icon: React.ComponentType
  onSelect: () => void
  shortcut?: string
  count?: number
}

export function CommandPalette() {
  const t = useT()
  const navigate = useNavigate()
  const board = useBoard()
  const listed = useProjects()
  const { refresh, newChat } = useConsole()
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
  const drafts = board.tickets.filter((ticket) => ticket.column === "draft").length
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")
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
      setSearch("")
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

  // A Diagnostic: the same dialog, its type already chosen — see `DiagnoseButton`.
  const diagnoseHref = () =>
    generateLinkByResource({
      resource: tickets,
      resourceAction: ActionList.create,
      defaultData: here ? { project: here.id, type: "diagnostic" } : { type: "diagnostic" },
    })

  useHotkeys({
    palette: () => change(!open),
    // Under a window — a form half written, a picker typed into — the key is
    // the window's. The palette is one: there it is a letter in its field.
    newTicket: () => {
      if (document.querySelector('[role="dialog"]') || !canAct()) return false
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

  // What is typed filters here, not in cmdk — see `palette-search.ts`.
  const words = terms(search)
  const offered: Action[] = [
    {
      value: t("Open or close the console"),
      keywords: ["console", "chat", "discussion"],
      icon: MessageCircle,
      onSelect: () => run(toggleTalk),
      shortcut: drawerKey.label,
    },
    {
      value: newTicket,
      keywords: ["create", "ticket"],
      icon: Plus,
      onSelect: () => go(newTicketHref()),
      shortcut: ticketKey.label,
    },
    {
      value: here ? t("Diagnose a problem of {{project}}", { project: here.name }) : t("Diagnose a problem"),
      keywords: ["diagnose", "diagnostic", "bug", "broken", "why"],
      icon: Stethoscope,
      onSelect: () => go(diagnoseHref()),
    },
    {
      value: t("New project"),
      keywords: ["create", "project"],
      icon: FolderPlus,
      onSelect: () => go(newProjectHref()),
    },
    { value: t("New idea"), keywords: ["create", "idea"], icon: Lightbulb, onSelect: () => go(newIdeaHref()) },
    { value: t("New goal"), keywords: ["create", "goal"], icon: Target, onSelect: () => go(newGoalHref()) },
    {
      value: t("New schedule"),
      keywords: ["create", "schedule", "recurring"],
      icon: CalendarClock,
      onSelect: () => go(newScheduleHref()),
    },
    // As the Conversations page starts one: a fresh conversation, in the drawer.
    {
      value: t("New conversation"),
      keywords: ["create", "conversation", "session", "chat"],
      icon: MessageSquarePlus,
      onSelect: () =>
        run(() => {
          void newChat()
          openTalk()
        }),
    },
    {
      value: t("Resynchronise now"),
      keywords: ["refresh", "sync"],
      icon: RefreshCw,
      onSelect: () => run(() => void refresh()),
    },
    // The columns waiting on you, gone through one ticket after another — see `ticket-series.tsx`.
    ...(blocked
      ? [
          {
            value: t("Unblock the tickets"),
            keywords: ["unblock", "blocked", "series"],
            icon: ListChecks,
            onSelect: () => run(() => openSeries("blocked")),
            count: blocked,
          },
        ]
      : []),
    ...(review
      ? [
          {
            value: t("Decide on the tickets in review"),
            keywords: ["decide", "review", "series"],
            icon: Scale,
            onSelect: () => run(() => openSeries("review")),
            count: review,
          },
        ]
      : []),
    ...(drafts
      ? [
          {
            value: t("Sort the drafts"),
            keywords: ["draft", "ready", "abandon", "series"],
            icon: FilePen,
            onSelect: () => run(() => openSeries("draft")),
            count: drafts,
          },
        ]
      : []),
  ]
  // A reader is offered what changes nothing: reading the board again.
  const actions = (canAct() ? offered : offered.filter((action) => action.icon === RefreshCw)).filter(
    ({ value, keywords }) => says([value, ...keywords], words)
  )
  const pages = PAGES.filter(({ name }) => says([t(name), name, "page"], words))
  const projects = (listed?.projects ?? []).filter((project) =>
    says([project.name, idOf(project), "project"], words)
  )
  const found = open ? ticketsFor(board.tickets, search) : []

  return (
    <CommandDialog
      open={open}
      onOpenChange={change}
      title={t("Command palette")}
      description={t("Find a page, a project or a ticket, or run an action.")}
      closeLabel={t("Close")}
      className="top-[20%] translate-y-0 sm:max-w-xl"
      shouldFilter={false}
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
      <CommandInput
        value={search}
        onValueChange={setSearch}
        placeholder={t("Type a page, a project, a ticket…")}
      />
      <CommandList className="max-h-[min(60vh,420px)]">
        <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>

        {actions.length ? (
          <CommandGroup heading={t("Actions")}>
            {actions.map(({ value, icon: Icon, onSelect, shortcut, count }) => (
              <CommandItem key={value} value={value} onSelect={onSelect}>
                <Icon />
                <span className="truncate">{value}</span>
                {shortcut ? <CommandShortcut>{shortcut}</CommandShortcut> : null}
                {count ? <CommandShortcut className="tracking-normal">{count}</CommandShortcut> : null}
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        {pages.length ? (
          <>
            {actions.length ? <CommandSeparator /> : null}
            <CommandGroup heading={t("Pages")}>
              {pages.map(({ name, icon: Icon, href }) => (
                <CommandItem key={name} value={t(name)} onSelect={() => go(href())}>
                  <Icon />
                  {t(name)}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}

        {projects.length ? (
          <>
            {actions.length || pages.length ? <CommandSeparator /> : null}
            <CommandGroup heading={t("Projects")}>
              {projects.map((project) => (
                <CommandItem
                  key={idOf(project)}
                  value={`${project.name} ${idOf(project)}`}
                  onSelect={() => go(projectHref(idOf(project)))}
                >
                  <FolderGit2 />
                  {project.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}

        {found.length ? (
          <>
            {actions.length || pages.length || projects.length ? <CommandSeparator /> : null}
            <CommandGroup heading={t("Tickets")}>
              {found.map((ticket) => (
                <CommandItem
                  key={ticket.id}
                  value={`${titleOf(ticket)} ${ticket.short} ${ticket.id}`}
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
