import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import type { Ticket } from "@/lib/types"

import { LaunchNow, ScheduledField } from "./ticket-settings"

/* « Scheduled for » in a ticket's view: the date set, moved or removed — and
 * « Launch now », which takes it away and nothing else. */

const world = vi.hoisted(() => ({
  dated: [] as [string, string][],
  patched: [] as [string, Record<string, unknown>][],
  launched: [] as string[],
  refuse: false,
  toasts: [] as string[],
}))

vi.mock(import("@/lib/role"), async (original) => ({ ...(await original()), canAct: () => true }))
vi.mock("sonner", () => ({ toast: { error: (said: string) => world.toasts.push(said) } }))
vi.mock("@/lib/api", () => ({
  api: {
    setScheduled: (ticket: string, scheduled: string) => {
      world.dated.push([ticket, scheduled])
      return world.refuse ? Promise.reject(new Error("refused")) : Promise.resolve({ id: ticket, scheduled })
    },
    launch: (ticket: string) => {
      world.launched.push(ticket)
      return Promise.resolve({ status: "started", message: "" })
    },
  },
  why: (error: Error) => error.message,
}))
vi.mock(import("@/lib/board-store"), async (original) => ({
  ...(await original()),
  useBoardWith: (() => undefined) as never,
  patchTicket: (id: string, patch: Record<string, unknown>) => void world.patched.push([id, patch]),
}))

const dated = {
  id: "abc",
  title: "A ticket",
  column: "ready",
  scheduled: "2099-01-01T09:00+01:00",
  held: { reason: "date", detail: "2099-01-01T09:00+01:00" },
} as unknown as Ticket

beforeEach(() => {
  world.dated = []
  world.patched = []
  world.launched = []
  world.refuse = false
  world.toasts = []
})

afterEach(cleanup)

describe("Launch now", () => {
  test("removes the date, and does not jump the queue", async () => {
    render(<LaunchNow ticket={dated} />)
    await userEvent.click(screen.getByRole("button", { name: "Launch now" }))
    await waitFor(() => expect(world.dated).toEqual([["abc", ""]]))
    expect(world.patched[0]).toEqual(["abc", { scheduled: "", held: undefined }])
    expect(world.launched).toEqual([])
  })

  test("puts the date back when the server refuses", async () => {
    world.refuse = true
    render(<LaunchNow ticket={dated} />)
    await userEvent.click(screen.getByRole("button", { name: "Launch now" }))
    await waitFor(() => expect(world.patched).toHaveLength(2))
    expect(world.patched[1]).toEqual(["abc", { scheduled: dated.scheduled, held: dated.held }])
    expect(world.toasts).toEqual(["The date could not be removed"])
  })
})

describe("the date in the view", () => {
  test("a shortcut chosen is written on Save, with the browser's offset", async () => {
    const undated = { ...dated, scheduled: "", held: undefined } as unknown as Ticket
    render(<ScheduledField ticket={undated}>never drawn</ScheduledField>)
    await userEvent.click(screen.getByRole("button", { name: "Change the date" }))
    await userEvent.click(screen.getByRole("button", { name: "Tomorrow morning" }))
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(world.dated).toHaveLength(1))
    const [[id, sent]] = world.dated
    expect(id).toBe("abc")
    expect(sent).toMatch(/^\d{4}-\d{2}-\d{2}T09:00[+-]\d{2}:\d{2}$/)
    expect(Date.parse(sent)).toBeGreaterThan(Date.now())
  })

  test("a moment already past is refused before anything is sent", async () => {
    render(<ScheduledField ticket={dated}>{"1 Jan 2099"}</ScheduledField>)
    await userEvent.click(screen.getByRole("button", { name: "Change the date" }))
    const field = screen.getByLabelText("Date and hour")
    await userEvent.clear(field)
    await userEvent.type(field, "2020-01-01T09:00")
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(world.toasts).toEqual(["This moment has already passed: choose a later one, or none."])
    expect(world.dated).toEqual([])
  })

  test("is no longer offered once the ticket is over", () => {
    render(<ScheduledField ticket={{ ...dated, column: "done" } as unknown as Ticket}>read only</ScheduledField>)
    expect(screen.queryByRole("button", { name: "Change the date" })).toBeNull()
    expect(screen.getByText("read only")).toBeTruthy()
  })
})
