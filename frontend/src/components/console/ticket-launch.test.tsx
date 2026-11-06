import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Ticket } from "@/lib/types"

import { RunNow } from "./ticket-launch"

/* « Run now » asks the daemon for a free place; when none is, the page says
 * why and offers to run the ticket past the limit, once — never by itself. */

const world = vi.hoisted(() => ({
  answers: [] as { status: string; message: string }[],
  asked: [] as [string, boolean][],
}))

vi.mock("@/lib/api", () => ({
  api: {
    launch: (ticket: string, force: boolean) => {
      world.asked.push([ticket, force])
      return Promise.resolve(world.answers.shift())
    },
  },
}))

vi.mock("@/lib/board-store", () => ({ titleOf: (ticket: { title: string }) => ticket.title }))

const ticket = { id: "abc", title: "A ticket", column: "ready" } as unknown as Ticket

beforeEach(() => {
  world.answers = []
  world.asked = []
})

describe("Run now", () => {
  test("takes a free place in one click", async () => {
    world.answers = [{ status: "started", message: "" }]
    render(<RunNow ticket={ticket} />)
    await userEvent.click(screen.getByRole("button", { name: "Run now" }))
    expect(world.asked).toEqual([["abc", false]])
    expect(screen.queryByText("No place is free")).toBeNull()
  })

  test("says why no place is free, and passes the limit only once it is confirmed", async () => {
    world.answers = [
      { status: "full", message: "all 2 place(s) are taken" },
      { status: "started", message: "" },
    ]
    render(<RunNow ticket={ticket} />)
    await userEvent.click(screen.getByRole("button", { name: "Run now" }))
    await waitFor(() => expect(screen.getByText("No place is free")).toBeTruthy())
    expect(screen.getByText(/All 2 places are taken/)).toBeTruthy()
    expect(world.asked).toEqual([["abc", false]])
    await userEvent.click(screen.getByRole("button", { name: "Run it past the limit" }))
    await waitFor(() => expect(world.asked).toEqual([["abc", false], ["abc", true]]))
  })
})
