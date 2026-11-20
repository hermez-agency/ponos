import * as React from "react"
import {
  ListCalendar,
  useNavigate,
  useViewLinkBuilder,
  type ListComponentPropsInterface,
  type RowInterface,
} from "react-resource-view"

import { RECURRENCE_COLOR, type AgendaEntry } from "@/lib/agenda-marks"
import { t } from "@/lib/i18n"
import { entries, zoneOf } from "@/lib/occurrences"
import { load, scheduleHref, useSchedules } from "@/resources/schedules"
import { tickets, type TicketItem } from "@/resources/tickets"

/* The Agenda: the board's tickets laid out on the days they are held until,
 * in the package's own calendar — the board and the List are the same rows,
 * this is where they fall in time. A ticket with no date programmed is not
 * on it: it has no day to be drawn on.
 *
 * The recurring tickets are drawn beside them, in their own colour and with
 * their own icon: the moments a schedule will write a ticket, walked forward
 * from its `Next` by the very rule the schedules' calendar uses
 * (`lib/occurrences.ts`). They are not tickets yet, so a click on one opens
 * the schedule, not a ticket.
 *
 * A click on an event opens what it is, at once — the ticket in the window it
 * opens in over the board, as a card or a row of the List does — rather than
 * the package's small preview first, which would make two clicks of what is
 * one everywhere else. The package hands no click of an event out, so each
 * event carries a mark in its icon (`lib/agenda-marks.tsx`), and the click is
 * taken on its way down, before the preview opens. A click on a day is the package's own:
 * a new ticket, held until that day.
 */

export function TicketAgenda({ rows = [] }: ListComponentPropsInterface<TicketItem>) {
  const { drawn } = useSchedules()
  // Read here when nobody has read them yet: the schedules' page keeps them
  // once read, and says so when a schedule changes.
  React.useEffect(() => {
    if (!drawn) void load().catch(() => null)
    const again = () => void load().catch(() => null)
    window.addEventListener("ponos:schedules", again)
    return () => window.removeEventListener("ponos:schedules", again)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, as the agenda opens: `drawn` is what the read writes
  }, [])

  const laid = React.useMemo(() => {
    const dated = rows.filter((row) => Boolean(row.data?.scheduled)) as RowInterface<AgendaEntry>[]
    if (!drawn) return dated
    const byId = new Map(drawn.schedules.map((schedule) => [schedule.id, schedule]))
    const upcoming = entries(drawn.schedules, Date.now(), zoneOf(drawn.timezone)).filter(
      (entry) => entry.kind === "upcoming"
    )
    const recurring = upcoming.map((entry): RowInterface<AgendaEntry> => {
      const name = byId.get(entry.schedule)?.name ?? ""
      return {
        data: {
          id: `recurrence:${entry.key}`,
          "@id": `recurrence:${entry.key}`,
          title:
            entry.times.length > 1
              ? t("{{count}} launches · {{name}}", { name, count: String(entry.times.length) })
              : name,
          scheduled: new Date(entry.start).toISOString(),
          color: RECURRENCE_COLOR,
          schedule: entry.schedule,
        },
      }
    })
    return [...dated, ...recurring]
  }, [rows, drawn])

  const navigate = useNavigate()
  const build = useViewLinkBuilder()
  const open = (event: React.MouseEvent<HTMLElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const mark = (event.target as HTMLElement)
      .closest("button")
      ?.querySelector("[data-agenda-ticket], [data-agenda-schedule]")
    if (!mark) return
    event.preventDefault()
    event.stopPropagation()
    const ticket = mark.getAttribute("data-agenda-ticket")
    if (ticket) {
      const link = build({ resource: tickets, action: "read", id: ticket })
      // So that closing the window is Back, and the focus comes back to the event.
      link.onOpen(event)
      void navigate({ to: link.to })
      return
    }
    void navigate({ to: scheduleHref(mark.getAttribute("data-agenda-schedule") ?? "") })
  }

  return (
    <div data-slot="ticket-agenda" className="min-w-0" onClickCapture={open}>
      <ListCalendar rows={laid} />
    </div>
  )
}
