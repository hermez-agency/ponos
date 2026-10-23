import { titleOf, useBoard } from "@/lib/board-store"
import { recordWindow } from "./record-window"
import { TicketGoal } from "./ticket-goal"

/* A ticket opened from the board, in a window over it.
 *
 * Opening a ticket used to leave the board: the page replaced it, and the way
 * back put you at the top of the cards — or of the table — whatever you were
 * reading. The window keeps the board where it was, under it, and the page is
 * one button away; the page's address is still the one a link shared, the
 * palette and a notification lead to.
 *
 * It is the `open` of the tickets' `read` view (see `tickets.tsx`): a card or a
 * row only links to the ticket, and react-resource-view writes it into the
 * address under the list and draws it in this. Its header says what the board
 * knows of the ticket — its short id, its whole title — before the ticket
 * itself is read — and, under the title, the goal it serves, a link to the
 * goal's page. A ticket that serves none has no line there at all.
 *
 * Not importing the tickets, which declare it: the declaration reads this as
 * it is built.
 */
export const ticketWindow = recordWindow({
  type: "ticket-window",
  fallbackTitle: "Ticket",
  // Anchored by its top edge, not centred on its own height: the title and the
  // tabs stay under the cursor when a tab is a shorter page than the other.
  className: "sm:top-[6dvh] sm:translate-y-0 sm:max-h-[calc(100dvh-6dvh-1rem)]",
  useHead: function useTicketHead(id) {
    const ticket = useBoard().tickets.find((item) => item.id === id)
    return {
      eyebrow: ticket ? `#${ticket.short}` : undefined,
      title: ticket ? titleOf(ticket) : "",
      description: ticket ? <TicketGoal ticket={ticket} /> : undefined,
    }
  },
})
