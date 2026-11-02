import { render } from "@testing-library/react"
import { describe, expect, test } from "vitest"

import type { Ticket } from "@/lib/types"

import { TicketHeld } from "./ticket-bits"

/* A ready card says why it waits only when the wait is out of the ordinary or
 * something can be done about it. The ordinary wait — the next reading, the
 * next run of the timer, every place taken — is the column's own state, said
 * once by « In progress N/max », not repeated on every card. */

const ready = (reason: string, detail = "") =>
  ({ id: "abc", title: "A ticket", column: "ready", held: { reason, detail } }) as unknown as Ticket

const said = (reason: string, detail = "") =>
  render(<TicketHeld ticket={ready(reason, detail)} />).container.querySelector(
    '[data-slot="ticket-held"]'
  )

describe("a ready card", () => {
  test.each(["pass", "next", "places", "project"])("says nothing of the ordinary wait: %s", (reason) => {
    expect(said(reason, "3")).toBeNull()
  })

  test.each([
    ["credits", "14:00", "out of credit"],
    ["budget", "00:00", "spending limit"],
    ["timer", "", "timer is off"],
    ["date", "2026-12-01", "scheduled for"],
  ])("still says why it waits: %s", (reason, detail, words) => {
    expect(said(reason, detail)?.textContent).toContain(words)
  })
})
