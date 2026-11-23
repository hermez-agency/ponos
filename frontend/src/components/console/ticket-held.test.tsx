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

const said = (reason: string, detail = "", card = false) =>
  render(<TicketHeld ticket={ready(reason, detail)} card={card} />).container.querySelector(
    '[data-slot="ticket-held"]'
  )

describe("a ready card", () => {
  test.each(["next", "places", "project"])("says nothing of the ordinary wait: %s", (reason) => {
    expect(said(reason, "3")).toBeNull()
  })

  test.each([
    ["credits", "14:00", "out of credit"],
    ["budget", "00:00", "spending limit"],
    ["daemon", "", "no daemon is running"],
    ["date", "2026-12-01", "scheduled for"],
  ])("still says why it waits: %s", (reason, detail, words) => {
    expect(said(reason, detail)?.textContent).toContain(words)
  })
})

/* No daemon running is the machine's state, not the card's: the band over the
 * board says it once (`DaemonBand`), and the ticket's own page still does. */
describe("a card of the board", () => {
  test("leaves the stopped daemon to the band over the columns", () => {
    expect(said("daemon", "", true)).toBeNull()
  })

  test.each([
    ["date", "2026-11-20", "scheduled for"],
    ["after", "Another ticket", "waiting for"],
    ["credits", "14:00", "out of credit"],
  ])("keeps the waits that are its own: %s", (reason, detail, words) => {
    expect(said(reason, detail, true)?.textContent).toContain(words)
  })
})
