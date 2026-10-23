import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Ticket } from "@/lib/types"

import StopGestures from "./ticket-stop"

/* The gestures of a ticket in progress and of one put aside: pausing is one
 * click, abandoning asks first, resuming asks too (its session is paid for).
 * Each is a move — the console ends the session before it writes the status. */

const world = vi.hoisted(() => ({
  columns: [] as { key: string; name: string }[],
  cancel: true,
  moved: [] as [string, string][],
}))

vi.mock("@/hooks/use-console", () => ({
  moveWithToast: (ticket: { id: string }, column: string) => {
    world.moved.push([ticket.id, column])
  },
}))

vi.mock("@/lib/board-store", () => ({
  titleOf: (ticket: { title: string }) => ticket.title,
  useBoard: () => ({ columns: world.columns, cancel: world.cancel, tickets: [] }),
}))

vi.mock("./ticket-bits", () => ({ columnTitle: (_key: string, name?: string) => name ?? "Ready" }))

const ticket = (column: string) => ({ id: "abc", title: "A ticket", column }) as unknown as Ticket

beforeEach(() => {
  world.columns = [
    { key: "ready", name: "Ready" },
    { key: "paused", name: "Paused" },
  ]
  world.cancel = true
  world.moved = []
})

describe("a ticket in progress", () => {
  test("is paused with one click", async () => {
    render(<StopGestures ticket={ticket("running")} />)
    await userEvent.click(screen.getByRole("button", { name: "Pause" }))
    expect(world.moved).toEqual([["abc", "paused"]])
  })

  test("is abandoned only once it is confirmed", async () => {
    render(<StopGestures ticket={ticket("running")} />)
    await userEvent.click(screen.getByRole("button", { name: "Abandon" }))
    expect(world.moved).toEqual([])
    expect(screen.getByText("This cannot be undone.")).toBeTruthy()
    await userEvent.click(screen.getAllByRole("button", { name: "Abandon" }).at(-1) as HTMLElement)
    expect(world.moved).toEqual([["abc", "cancelled"]])
  })

  test("offers only what the board can say, and nothing at all without either", () => {
    world.columns = [{ key: "ready", name: "Ready" }]
    const { container, rerender } = render(<StopGestures ticket={ticket("running")} />)
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull()
    expect(screen.getByRole("button", { name: "Abandon" })).toBeTruthy()
    world.cancel = false
    rerender(<StopGestures ticket={ticket("running")} />)
    expect(container.innerHTML).toBe("")
  })
})

describe("a paused ticket", () => {
  test("is resumed to ready once it is confirmed", async () => {
    render(<StopGestures ticket={ticket("paused")} />)
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "Resume" }))
    expect(world.moved).toEqual([])
    await userEvent.click(screen.getByRole("button", { name: "Make it ready" }))
    expect(world.moved).toEqual([["abc", "ready"]])
  })
})
