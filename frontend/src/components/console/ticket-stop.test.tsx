import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Ticket } from "@/lib/types"

import StopGestures from "./ticket-stop"

/* The gestures of a ticket in progress and of one put aside: pausing is one
 * click, abandoning waits behind "…" and asks first, on Cancel, resuming asks
 * too (its session is paid for). Each is a move — the console ends the session
 * before it writes the status. */

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
  useBoardWith: <T,>(select: (board: unknown) => T) =>
    select({ columns: world.columns, cancel: world.cancel, tickets: [] }),
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

  test("keeps abandoning out of sight, apart from pausing", () => {
    render(<StopGestures ticket={ticket("running")} />)
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Abandon" })).toBeNull()
    expect(screen.getByRole("button", { name: "More actions" })).toBeTruthy()
  })

  test("is abandoned from the menu, in red, only once it is confirmed", async () => {
    const user = userEvent.setup()
    render(<StopGestures ticket={ticket("running")} />)
    await user.click(screen.getByRole("button", { name: "More actions" }))
    const item = await screen.findByRole("menuitem", { name: "Abandon" })
    expect(item.getAttribute("data-variant")).toBe("destructive")
    await user.click(item)
    expect(world.moved).toEqual([])
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog.textContent).toContain("Abandon “A ticket”?")
    expect(dialog.textContent).toContain(
      "The session in progress is stopped, and the work it has not pushed is lost. This cannot be undone."
    )
    await user.click(screen.getByRole("button", { name: "Abandon the ticket" }))
    expect(world.moved).toEqual([["abc", "cancelled"]])
  })

  test("opens its confirmation on Cancel, where Enter takes nothing away", async () => {
    const user = userEvent.setup()
    render(<StopGestures ticket={ticket("running")} />)
    await user.click(screen.getByRole("button", { name: "More actions" }))
    await user.click(await screen.findByRole("menuitem", { name: "Abandon" }))
    const cancel = await screen.findByRole("button", { name: /^Cancel/ })
    expect(document.activeElement).toBe(cancel)
    // The main button says nothing of Enter, which does not press it here.
    const abandon = screen.getByRole("button", { name: "Abandon the ticket" })
    expect(abandon.getAttribute("aria-keyshortcuts")).toBeNull()
    expect(abandon.className).toContain("destructive")
    await user.keyboard("{Enter}")
    expect(world.moved).toEqual([])
    expect(screen.queryByRole("alertdialog")).toBeNull()
  })

  test("offers only what the board can say, and nothing at all without either", () => {
    world.columns = [{ key: "ready", name: "Ready" }]
    const { container, rerender } = render(<StopGestures ticket={ticket("running")} />)
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull()
    expect(screen.getByRole("button", { name: "More actions" })).toBeTruthy()
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

  test("is abandoned the same way, and told only what is lost without a session", async () => {
    const user = userEvent.setup()
    render(<StopGestures ticket={ticket("paused")} />)
    expect(screen.queryByRole("button", { name: "Abandon" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "More actions" }))
    await user.click(await screen.findByRole("menuitem", { name: "Abandon" }))
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog.textContent).toContain("The work that was not pushed is lost. This cannot be undone.")
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Cancel/ }))
    await user.click(screen.getByRole("button", { name: "Abandon the ticket" }))
    expect(world.moved).toEqual([["abc", "cancelled"]])
  })
})
