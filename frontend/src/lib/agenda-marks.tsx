import * as React from "react"
import { CalendarClock, Repeat, type LucideIcon, type LucideProps } from "lucide-react"
import type { RowInterface } from "react-resource-view"

/* What a click on an event of the Agenda opens, written on the event itself.
 *
 * The package's calendar draws each event as a button of its own that opens a
 * small preview, and hands neither the click nor the row out. What it does
 * draw for each row is an icon, from the layout's `getIcon` — so the icon is
 * where the row says what it is: a ticket, or a moment a schedule writes one,
 * with its id. `TicketAgenda` reads it back from the button clicked.
 *
 * Apart from the agenda, which is fetched when it is first drawn: `getIcon` is
 * declared with the resource, on the first load, and this is all it needs. */

/** The colour of a recurrence's moments: apart from the tickets', which are the console's own. */
export const RECURRENCE_COLOR = "#8b5cf6"

/** A moment a schedule will write a ticket at: not a ticket yet. */
export interface Recurrence {
  id: string
  "@id": string
  title: string
  scheduled: string
  color: string
  /** The schedule the moment is one of. */
  schedule: string
}

/** What the calendar lays out: a ticket's row, or a moment of a schedule. */
export type AgendaEntry = Recurrence | { id: string; "@id": string; title: string; scheduled: string }

const isRecurrence = (data: Record<string, unknown>): boolean =>
  typeof data.schedule === "string" && data.color === RECURRENCE_COLOR

/* One component per ticket or schedule for the life of the page, so that an
 * event drawn again is the same element and not a new one. */
const marks = new Map<string, LucideIcon>()

function markOf(kind: "ticket" | "schedule", id: string): LucideIcon {
  const key = `${kind}:${id}`
  let mark = marks.get(key)
  if (!mark) {
    const Icon = kind === "ticket" ? CalendarClock : Repeat
    const attribute = kind === "ticket" ? { "data-agenda-ticket": id } : { "data-agenda-schedule": id }
    mark = React.forwardRef<SVGSVGElement, LucideProps>((props, ref) => <Icon ref={ref} {...props} {...attribute} />) as LucideIcon
    marks.set(key, mark)
  }
  return mark
}

/** The icon the Agenda draws on an event: the mark of what a click on it opens. */
export function agendaIcon(row: RowInterface<Record<string, unknown>>): LucideIcon | undefined {
  const data = row.data
  if (!data?.id) return undefined
  return isRecurrence(data) ? markOf("schedule", String(data.schedule)) : markOf("ticket", String(data.id))
}
