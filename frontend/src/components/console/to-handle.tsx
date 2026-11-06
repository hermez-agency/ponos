import * as React from "react"
import { ServerCrash } from "lucide-react"
import { Link } from "react-resource-view"

import { Button } from "@/components/ui/button"
import { Eyebrow } from "@/components/console/frame"
import { useOpensOverTheList } from "@/components/console/record-window"
import {
  FAMILY_ICON,
  SEED,
  TicketActions,
  TicketCi,
  ago,
  blockSaid,
  capital,
  columnTitle,
  familyColor,
} from "@/components/console/ticket-bits"
import { SeriesButton } from "@/components/console/ticket-decision"
import { useBoard } from "@/lib/board-store"
import { counted, useT } from "@/lib/i18n"
import { toHandle } from "@/lib/to-handle"
import type { Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { ticketHref, tickets } from "@/resources/tickets"

/* What waits for you, first thing on a phone.
 *
 * Measured at 375 × 812 on the audit of November 2026: the board started
 * 1 725 px down, under the health band and two screens of figures, and its
 * Blocked column was the fourth one across — three swipes past 35 drafts and
 * 16 ready tickets to see what waited on an answer. The menu's badge and the
 * bell counted those tickets; nothing showed them together.
 *
 * So on a phone the dashboard opens on them: the blocked tickets and the ones
 * in review, one card each, in the order `to-handle.ts` gives — a blocked one
 * first, the one waiting longest first. A card says why it waits, and carries
 * the gestures the board's card has (`TicketActions`): Unblock opens the
 * discussion on the question and its quick replies, Decide the numbered
 * choices of the pull request — one tap there, one on the answer. A column of
 * them at once goes through the series (`SeriesButton`), from the heading.
 *
 * The first few only: twenty tickets in flight leave a dozen waiting, and the
 * figures and the board are under them. The rest is one tap further.
 */

/** How many cards the block draws before it offers the rest. */
const SHOWN = 4

export function ToHandle() {
  const t = useT()
  const board = useBoard()
  const [all, setAll] = React.useState(false)
  const waiting = React.useMemo(() => toHandle(board.tickets), [board.tickets])
  const drawn = all ? waiting : waiting.slice(0, SHOWN)
  const left = waiting.length - drawn.length
  return (
    <section data-slot="to-handle" aria-labelledby="to-handle-title" className="mb-4 flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="to-handle-title" className="flex items-center gap-2">
          <Eyebrow>{t("To handle")}</Eyebrow>
          {waiting.length ? (
            <span className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-xs tabular-nums">
              {waiting.length}
            </span>
          ) : null}
        </h2>
        <div className="flex items-center gap-1.5">
          <SeriesButton column="blocked" />
          <SeriesButton column="review" />
        </div>
      </div>
      {waiting.length ? (
        <ul className="flex flex-col gap-2">
          {drawn.map((ticket) => (
            <HandleCard key={ticket.id} ticket={ticket} />
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground text-sm">{t("Nothing waits for you: no ticket is blocked or in review.")}</p>
      )}
      {left > 0 ? (
        <Button variant="outline" size="sm" onClick={() => setAll(true)}>
          {counted(left, "Show the other one", "Show the {{count}} others")}
        </Button>
      ) : null}
    </section>
  )
}

/** One ticket waiting: where it stands and since when, its title, why it waits, and what to do. */
function HandleCard({ ticket }: { ticket: Ticket }) {
  const board = useBoard()
  // The ticket's window over the dashboard, as a card of the board opens it.
  const open = useOpensOverTheList(tickets, "read", ticket.id)
  const href = ticketHref(ticket.id)
  const column = board.columns.find((one) => one.key === ticket.column)
  const block = ticket.column === "blocked" ? ticket.block : null
  const Icon = block ? (FAMILY_ICON[block.family] ?? ServerCrash) : null
  return (
    <li
      data-handle-card={ticket.id}
      data-handle-column={ticket.column}
      className="bg-card flex min-w-0 flex-col gap-1.5 rounded-xl border p-3"
    >
      <div className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
        <span className={cn("size-1.5 shrink-0 rounded-full", SEED[ticket.column] ?? "bg-muted-foreground")} />
        <span className="shrink-0">{capital(columnTitle(ticket.column, column?.name))}</span>
        {ticket.project ? <span className="min-w-0 truncate">· {ticket.project}</span> : null}
        <span className="ms-auto shrink-0 tabular-nums">{ago(ticket.edited)}</span>
      </div>
      <Link
        to={href}
        onClick={open}
        className="line-clamp-2 text-[0.93rem] leading-snug font-semibold break-words hover:underline"
      >
        {ticket.title}
      </Link>
      {block && Icon ? (
        <p className="flex min-w-0 items-start gap-1.5 text-sm leading-snug" data-code={block.code}>
          <Icon className="mt-0.5 size-3.5 shrink-0" style={{ color: familyColor(block.family) }} aria-hidden />
          <span className="min-w-0">
            <span className="font-medium">{blockSaid(block.label)}</span>
            {block.help ? (
              <span className="text-muted-foreground line-clamp-2 text-xs">{blockSaid(block.help)}</span>
            ) : null}
          </span>
        </p>
      ) : null}
      {ticket.column === "review" ? <TicketCi ci={ticket.ci} /> : null}
      <TicketActions ticket={ticket} answer={{ href, onClick: open }} />
    </li>
  )
}
