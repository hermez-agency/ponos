import { Link } from "@tanstack/react-router"

import { useT } from "@/lib/i18n"
import { upcoming } from "@/lib/later"
import type { AwaitedTicket, Ticket } from "@/lib/types"
import { ticketHref } from "@/resources/tickets"

import { Chip, LABEL, when } from "./ticket-bits"

/* What a waiting ticket waits for, said on its card and at the top of its page.
 *
 * A waiting ticket is one whose moment has not come (`config.STATUS` on the
 * server): a date still ahead, tickets it comes after (« Après ») not finished
 * yet, or both. The column says *that* it waits; this says for what — « Starts
 * on 30 Nov, 09:00 », « Waits for PON-36 (in progress) » — each ticket waited
 * for a link to it. Nothing is drawn for a ticket that waits for nothing any
 * more: the daemon makes it ready at its next look. */

/** The columns a ticket waited for counts as finished in: validated is a review passed. */
export const FINISHED = ["done", "validated"]

/** The tickets it still waits for, in their order. */
export const unfinished = (ticket: Pick<Ticket, "after">): AwaitedTicket[] =>
  (ticket.after ?? []).filter((one) => !FINISHED.includes(one.column))

/** One ticket waited for: its id said out loud, where it stands, and the way to it. */
export function AwaitedLink({ awaited }: { awaited: AwaitedTicket }) {
  const t = useT()
  const column = LABEL[awaited.column] ? t(LABEL[awaited.column]).toLowerCase() : awaited.column
  return (
    <Link
      to={ticketHref(awaited.id)}
      draggable={false}
      title={awaited.title}
      data-slot="ticket-awaited"
      className="text-foreground font-medium underline-offset-2 hover:underline"
    >
      {awaited.public_id || awaited.title || awaited.id.slice(0, 8)}{" "}
      <span className="text-muted-foreground font-normal">({column})</span>
    </Link>
  )
}

export function TicketWaits({ ticket }: { ticket: Ticket }) {
  const t = useT()
  if (ticket.column !== "waiting") return null
  const dated = upcoming(ticket.scheduled, Date.now())
  const awaited = unfinished(ticket)
  if (!dated && !awaited.length) return null
  return (
    <div data-slot="ticket-waits" className="flex flex-wrap items-center gap-1.5 text-xs">
      {dated ? (
        <Chip className="whitespace-normal">⏱ {t("Starts {{at}}", { at: when(ticket.scheduled) })}</Chip>
      ) : null}
      {awaited.length ? (
        <span className="text-muted-foreground flex flex-wrap items-center gap-x-1.5">
          {t("Waits for")}
          {awaited.map((one, index) => (
            <span key={one.id}>
              <AwaitedLink awaited={one} />
              {index < awaited.length - 1 ? "," : ""}
            </span>
          ))}
        </span>
      ) : null}
    </div>
  )
}
