import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { TicketDetail } from "@/lib/types"

import { TicketOn } from "./ticket-on"

/* The « On » editor of a ticket's page: written, saved, emptied to remove the
 * prompt — and shown as it is, unchangeable, to whoever may not act. */

const world = vi.hoisted(() => ({ acts: true, saved: [] as string[] }))

vi.mock("@/lib/api", () => ({
  api: {
    transitions: () => Promise.resolve({ transitions: [] }),
    setOn: (_id: string, on: string) => {
      world.saved.push(on)
      return Promise.resolve({})
    },
  },
  why: (error: unknown) => String(error),
}))
vi.mock("@/lib/role", async (original) => ({
  ...(await original<typeof import("@/lib/role")>()),
  canAct: () => world.acts,
}))
vi.mock("sonner", () => ({ toast: { success: () => undefined, error: () => undefined } }))

const ticket = (on: string) =>
  ({ id: "abc", status: "Done", edited: "2026-11-13T10:00:00Z", on }) as unknown as TicketDetail

beforeEach(() => {
  world.acts = true
  world.saved = []
})

describe("the On editor", () => {
  test("is filled with the current prompt, and saves what is typed", async () => {
    render(<TicketOn ticket={ticket("Create the follow-up.")} />)
    const box = screen.getByRole("textbox", { name: "Prompt on status change" })
    expect((box as HTMLTextAreaElement).value).toBe("Create the follow-up.")
    await userEvent.clear(box)
    await userEvent.type(box, "Deploy it.")
    await userEvent.click(screen.getByRole("button", { name: "Save the prompt" }))
    await waitFor(() => expect(world.saved).toEqual(["Deploy it."]))
  })

  test("emptied, it saves an empty prompt, which removes it", async () => {
    render(<TicketOn ticket={ticket("Create the follow-up.")} />)
    await userEvent.clear(screen.getByRole("textbox", { name: "Prompt on status change" }))
    await userEvent.click(screen.getByRole("button", { name: "Save the prompt" }))
    await waitFor(() => expect(world.saved).toEqual([""]))
  })

  test("shows a reader the prompt without a way to change it", () => {
    world.acts = false
    render(<TicketOn ticket={ticket("Create the follow-up.")} />)
    const box = screen.getByRole("textbox", { name: "Prompt on status change" }) as HTMLTextAreaElement
    expect(box.readOnly).toBe(true)
    expect(screen.queryByRole("button", { name: "Save the prompt" })).toBeNull()
  })

  test("tells a reader there is no prompt rather than drawing an empty box", () => {
    world.acts = false
    render(<TicketOn ticket={ticket("")} />)
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.getByText("No prompt on this ticket.")).toBeTruthy()
  })
})
