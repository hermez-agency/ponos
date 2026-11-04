import * as React from "react"
import { ListChecks, MessageCircleQuestion, Scale, type LucideIcon } from "lucide-react"
import { useLocation } from "@tanstack/react-router"
import { useNavigate } from "react-resource-view"

import { Button } from "@/components/ui/button"
import { useOpensOverTheList } from "@/components/console/record-window"
import { useBoard } from "@/lib/board-store"
import { type DecisionTab, actionOf, decisionTabOf } from "@/lib/decision"
import { useT } from "@/lib/i18n"
import { SERIES_FROM, type SeriesColumn, withSeries } from "@/lib/series"
import type { Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { tickets } from "@/resources/tickets"

/* What a card waiting on you is for: why it waits, and what to do about it.
 * A blocked card used to offer "make ready" and nothing else, and one in review
 * three gestures that said nothing of what they were deciding on: the reason was
 * in the last report, on the page. This reads that report for you — the server
 * does, see `decisions.py` — and lays out the few choices that fit, each a click,
 * or a click and a sentence.
 *
 * In review, it is a tab of the ticket — Decide — beside its brief, its
 * discussion and its session. A blocked ticket had one too, Unblock, and it
 * said the question twice and offered two fields to answer it in, beside the
 * discussion that was already a conversation: its question is answered there
 * now, in the bubble Ponos asked it in and the quick replies under it — see
 * `ticket-talk.tsx`. The button on a card opens the window on the tab, or on
 * the discussion; the same button on the ticket itself, in its window or on
 * its page, only switches to it.
 *
 * The series that goes through a column's tickets one after another
 * (`ticket-series.tsx`) draws this panel for each, a blocked one too: its
 * question as the discussion says it, and under it every way out the server
 * offers, each numbered — the keys 1 to 9 there, in either column.
 *
 * The buttons are here, drawn on the board's cards; the panel they lead to is
 * in `ticket-decision-panel.tsx`, fetched with the ticket's page or the series.
 */

/** How a ticket shown on screen goes to one of its tabs: none around a card, which opens the window instead. */
/* The tab of a ticket opened in the window over a list, in the address. Not
 * `tab`, which is the page's under the window: a project names its own tabs
 * with it, and has a "brief" too. */
export const WINDOW_TAB = "ticket-tab"

export const TicketTabContext = React.createContext<{
  goTo: (tab: DecisionTab) => void
  /** The tab on show, which the button has no use to offer a second time. */
  shown?: string
} | null>(null)

/** The call to action of a card waiting on you: Unblock, or Decide. Nothing on any other card. */
export function DecideButton({
  ticket,
  className,
  title,
  icon,
}: {
  ticket: Ticket
  className?: string
  /** The tooltip: on a blocked card, the cause's label and its line of help, which the card no longer shows. */
  title?: string
  /** The mark of the cause on a blocked card, in place of the generic question mark. */
  icon?: LucideIcon
}) {
  const t = useT()
  const tabs = React.useContext(TicketTabContext)
  const action = actionOf(ticket.column)
  const tab = decisionTabOf(ticket.column)
  // Off the ticket's page, the window over the list, on that tab.
  const openOnTheTab = useOpensOverTheList(tickets, "read", ticket.id, tab ? `${WINDOW_TAB}=${tab}` : "")
  if (!action || !tab) return null
  // Already on that tab: the button would only point at where you are.
  if (tabs?.shown === tab) return null
  // On the ticket itself, Decide is a tab, with its mark: a button beside it
  // said the same word a second time. Unblock has no tab, and stays.
  if (tabs && tab === "decide") return null
  const blocked = ticket.column === "blocked"
  const Icon = blocked ? (icon ?? MessageCircleQuestion) : Scale
  return (
    <Button
      size="sm"
      variant="outline"
      data-decide={ticket.id}
      title={title}
      className={cn(
        blocked ? "text-tr-amber hover:text-tr-amber" : "text-tr-pink hover:text-tr-pink",
        className
      )}
      onClick={(event) => (tabs ? tabs.goTo(tab) : openOnTheTab(event))}
    >
      <Icon />
      {t(action)}
    </Button>
  )
}

/** Opens the series of a column's tickets over the page you are on: the address says it, so Back closes it. */
export function useOpenSeries() {
  const navigate = useNavigate()
  const { pathname, searchStr } = useLocation()
  return React.useCallback(
    (column: SeriesColumn) => void navigate({ to: `${pathname}${withSeries(searchStr, column)}` }),
    [navigate, pathname, searchStr]
  )
}

/* The way through a whole column at once, in its heading: Unblock (3), Decide
 * (2) — from two cards on, one being a card you would open anyway. Counted on
 * the board, whatever the search keeps. */
export function SeriesButton({ column }: { column: SeriesColumn }) {
  const t = useT()
  const board = useBoard()
  const open = useOpenSeries()
  const count = board.tickets.filter((ticket) => ticket.column === column).length
  if (count < SERIES_FROM) return null
  const blocked = column === "blocked"
  const Icon = blocked ? ListChecks : Scale
  return (
    <Button
      size="xs"
      variant="outline"
      data-series={column}
      className={cn("shrink-0", blocked ? "text-tr-amber hover:text-tr-amber" : "text-tr-pink hover:text-tr-pink")}
      onClick={(event) => {
        event.stopPropagation()
        open(column)
      }}
    >
      <Icon />
      {blocked ? t("Unblock ({{count}})", { count: String(count) }) : t("Decide ({{count}})", { count: String(count) })}
    </Button>
  )
}
