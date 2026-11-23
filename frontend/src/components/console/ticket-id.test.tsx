import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import { TicketId } from "./ticket-id"

/* A click on the id puts it on the clipboard, says "Copied" and does nothing
 * else — least of all open the ticket whose link it sits in. */

const world = vi.hoisted(() => ({ copied: [] as string[], toasts: [] as string[], opened: 0 }))

vi.mock("@/lib/clipboard", () => ({
  toClipboard: (text: string) => {
    world.copied.push(text)
    return Promise.resolve(true)
  },
}))
vi.mock("sonner", () => ({
  toast: {
    success: (message: string, options?: { description?: string }) =>
      world.toasts.push(`${message} ${options?.description ?? ""}`.trim()),
    error: vi.fn(),
  },
}))

beforeEach(() => {
  world.copied = []
  world.toasts = []
  world.opened = 0
})

describe("TicketId", () => {
  test("copies the id on click, says so, and is named for a screen reader", async () => {
    render(<TicketId id="PON-142" />)
    await userEvent.click(screen.getByRole("button", { name: "Copy the id PON-142" }))
    await waitFor(() => expect(world.copied).toEqual(["PON-142"]))
    expect(world.toasts).toEqual(["Copied PON-142"])
    expect(screen.getByText("PON-142")).toBeTruthy()
  })

  test("does not open the link it sits in", async () => {
    render(
      <a href="#ticket" onClick={() => (world.opened += 1)}>
        A title <TicketId id="BA-37" />
      </a>
    )
    await userEvent.click(screen.getByText("BA-37"))
    expect(world.copied).toEqual(["BA-37"])
    expect(world.opened).toBe(0)
  })

  test("draws nothing for a ticket without a public id", () => {
    const { container } = render(<TicketId id="" />)
    expect(container.innerHTML).toBe("")
  })
})
