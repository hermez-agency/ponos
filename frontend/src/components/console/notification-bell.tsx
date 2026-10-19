import * as React from "react"
import {
  BellIcon,
  CircleHelpIcon,
  GitPullRequestIcon,
  HandIcon,
  ShieldXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { useNavigate } from "react-resource-view"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/api"
import { titleOf, useBoard } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { badgeLabel } from "@/lib/notifications"
import { publishBell, useBell } from "@/lib/notifications-store"
import type { Notification, NotificationKind } from "@/lib/types"
import { cn } from "@/lib/utils"
import { ticketHref } from "@/resources/tickets"
import { ago } from "./ticket-bits"

/* The bell in the header: what asks for your attention, without a view of its own.
 *
 * The runner writes a notification when a session stops on a question, a pull
 * request is ready to read, its checks are red, a session fails or a ticket is
 * blocked — and nothing for the routine (a ticket taken, a ticket in progress).
 * They reach this page on the stream like the board does, so opening the panel
 * asks for nothing. A click opens the ticket's card and marks that one read; both
 * the read marks and "Mark all as read" are kept by the server, so a reload
 * keeps them.
 */

const ICONS: Record<NotificationKind, typeof BellIcon> = {
  question: CircleHelpIcon,
  review: GitPullRequestIcon,
  ci: ShieldXIcon,
  failed: TriangleAlertIcon,
  blocked: HandIcon,
}

const TONES: Record<NotificationKind, string> = {
  question: "text-tr-amber",
  review: "text-tr-green",
  ci: "text-tr-red",
  failed: "text-tr-red",
  blocked: "text-tr-amber",
}

export function NotificationBell() {
  const t = useT()
  const { unread } = useBell()
  const [open, setOpen] = React.useState(false)
  const label = badgeLabel(unread)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="relative"
              aria-label={
                unread ? t("Notifications, {{count}} unread", { count: String(unread) }) : t("Notifications")
              }
            >
              <BellIcon />
              {label ? (
                <span
                  aria-hidden
                  data-testid="bell-badge"
                  className="bg-tr-red absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 font-mono text-[0.6rem] leading-none text-white dark:text-background"
                >
                  {label}
                </span>
              ) : null}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("what asks for your attention")}</TooltipContent>
      </Tooltip>
      <PopoverContent
        align="end"
        className="w-[min(24rem,calc(100vw-1rem))] gap-0 p-0"
        aria-label={t("Notifications")}
      >
        <Panel close={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}

/* Drawn only while open: it reads the board for the project of each ticket, and
 * a closed bell must not be drawn again every time the board moves. */
function Panel({ close }: { close: () => void }) {
  const t = useT()
  const { items, unread } = useBell()
  const board = useBoard()
  const navigate = useNavigate()
  const known = React.useMemo(() => new Map(board.tickets.map((item) => [item.id, item])), [board])

  const read = (id?: number) => void api.readNotifications(id).then(publishBell, () => {})
  const open = (item: Notification) => {
    if (!item.read) read(item.id)
    close()
    void navigate({ to: ticketHref(item.ticket) })
  }

  const words: Record<NotificationKind, string> = {
    question: t("A session is waiting for your answer"),
    review: t("A pull request is ready to read"),
    ci: t("The checks of a pull request fail"),
    failed: t("A session failed"),
    blocked: t("A ticket is blocked"),
  }

  return (
    <div className="flex max-h-[min(32rem,70dvh)] flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-sm font-medium">{t("Notifications")}</h2>
        <Button variant="ghost" size="sm" disabled={!unread} onClick={() => read()}>
          {t("Mark all as read")}
        </Button>
      </div>
      {items.length ? (
        <ul className="overflow-y-auto">
          {items.map((item) => {
            const Icon = ICONS[item.kind]
            const ticket = known.get(item.ticket)
            const when = ago(item.at)
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => open(item)}
                  data-unread={item.read ? undefined : ""}
                  className="hover:bg-accent focus-visible:bg-accent flex w-full items-start gap-3 px-3 py-2.5 text-left outline-hidden"
                >
                  <Icon className={cn("mt-0.5 size-4 shrink-0", TONES[item.kind])} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate text-sm", !item.read && "font-medium")}>
                      {ticket ? titleOf(ticket) : item.title || t("(untitled ticket)")}
                    </span>
                    <span className="text-muted-foreground block truncate text-xs">
                      {[words[item.kind], ticket?.project, when].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  {item.read ? null : (
                    <span className="bg-primary mt-1.5 size-2 shrink-0 rounded-full" aria-label={t("unread")} />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-muted-foreground px-3 py-6 text-center text-sm">{t("Nothing needs you.")}</p>
      )}
    </div>
  )
}
