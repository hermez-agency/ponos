import { render } from "@testing-library/react"
import { describe, expect, test } from "vitest"

import { tickets } from "@/resources/tickets"

import { agendaIcon, RECURRENCE_COLOR } from "./agenda-marks"

/* The Agenda reads what a click opens from the icon of the event clicked:
 * a ticket's id, or a schedule's. The same component for the same row, so an
 * event drawn again is not a new element. */

describe("the agenda's marks", () => {
  test("a ticket's event carries its id, and the same icon every time", () => {
    const Icon = agendaIcon({ data: { id: "abc", title: "A ticket", scheduled: "2026-11-21T09:00:00Z" } })
    expect(Icon).toBeDefined()
    expect(agendaIcon({ data: { id: "abc", title: "Renamed" } })).toBe(Icon)
    const { container } = render(Icon ? <Icon className="size-3" /> : null)
    expect(container.querySelector("[data-agenda-ticket]")?.getAttribute("data-agenda-ticket")).toBe("abc")
  })

  test("a recurrence's moment carries its schedule, not a ticket", () => {
    const Icon = agendaIcon({
      data: { id: "recurrence:s1@1", title: "Nightly", scheduled: "2026-11-21T03:00:00Z", color: RECURRENCE_COLOR, schedule: "s1" },
    })
    const { container } = render(Icon ? <Icon /> : null)
    expect(container.querySelector("[data-agenda-schedule]")?.getAttribute("data-agenda-schedule")).toBe("s1")
    expect(container.querySelector("[data-agenda-ticket]")).toBeNull()
  })

  test("the board offers three views — Board, List, Agenda — and the fields menu on its list", () => {
    const list = tickets.views?.list as unknown as {
      layouts: { id: string; label?: string; options?: { dateField?: string } }[]
      fields?: { toggle?: boolean; persist?: string | false }
    }
    expect(list.layouts.map((each) => each.label)).toEqual(["Columns", "List", "Agenda"])
    expect(list.layouts.map((each) => each.id)).toEqual(["board", "table", "calendar"])
    expect(list.layouts[2].options?.dateField).toBe("scheduled")
    expect(list.fields).toMatchObject({ toggle: true, persist: "local" })
  })
})
