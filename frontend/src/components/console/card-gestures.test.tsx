import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Board, Ticket } from "@/lib/types"

import { TicketActions } from "./ticket-bits"

/* The gestures on a card of the board: one filled button at most, for what the
 * ticket waits for, and every other gesture behind "…" — the same dialogs and
 * the same moves as the buttons of the ticket's page. */

const world = vi.hoisted(() => ({ moved: [] as [string, string][] }))

vi.mock(import("@/hooks/use-console"), async (importOriginal) => ({
  ...(await importOriginal()),
  moveWithToast: async (ticket: { id: string }, column: string) => {
    world.moved.push([ticket.id, column])
  },
}))

vi.mock(import("@/lib/role"), async (importOriginal) => ({ ...(await importOriginal()), canAct: () => true }))

const COLUMNS = ["draft", "ready", "running", "paused", "blocked", "review", "validated", "done", "cancelled"]

vi.mock(import("@/lib/board-store"), async (importOriginal) => ({
  ...(await importOriginal()),
  titleOf: (ticket: { title: string }) => ticket.title,
  useBoardWith: <T,>(select: (board: Board) => T) =>
    select({
      columns: COLUMNS.map((key) => ({ key, name: key })),
      validate: true,
      cancel: true,
      tickets: [],
    } as unknown as Board),
}))

vi.mock(import("@/components/console/record-window"), async (importOriginal) => ({
  ...(await importOriginal()),
  useOpensOverTheList: () => () => {},
}))

const ticket = (column: string, more: Partial<Ticket> = {}) =>
  ({ id: "abc", title: "A ticket", column, pull_request: "", ...more }) as unknown as Ticket

const filled = (container: HTMLElement) => container.querySelectorAll('button[data-variant="default"]')

beforeEach(() => {
  world.moved = []
})

describe("a card of the board", () => {
  test.each([
    ["draft", "Make ready"],
    ["blocked", "Unblock"],
    ["review", "Decide"],
  ])("in %s has one filled button: %s", (column, label) => {
    const { container } = render(<TicketActions ticket={ticket(column)} card />)
    const buttons = filled(container)
    expect(buttons).toHaveLength(1)
    expect(buttons[0].textContent).toContain(label)
  })

  test("blocked on a refused merge, it retries it from its menu, beside Unblock", async () => {
    const user = userEvent.setup()
    const refused = ticket("blocked", {
      pull_request: "https://github.com/o/r/pull/1",
      block: { code: "merge.refused", family: "merge", label: { en: "", fr: "" }, help: { en: "", fr: "" } },
    } as Partial<Ticket>)
    const { container } = render(<TicketActions ticket={refused} card />)
    expect(filled(container)).toHaveLength(1)
    expect(screen.queryByRole("button", { name: "Retry the merge" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "More actions" }))
    await user.click(await screen.findByRole("menuitem", { name: "Back to review" }))
    expect(world.moved).toEqual([["abc", "review"]])
  })

  test("in progress, its one filled button is Pause", async () => {
    const { container } = render(<TicketActions ticket={ticket("running")} card />)
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy()
    expect(filled(container)).toHaveLength(1)
  })

  test("ready, it runs now from an outline, and is set aside from its menu", async () => {
    const user = userEvent.setup()
    const { container } = render(<TicketActions ticket={ticket("ready")} card />)
    expect(filled(container)).toHaveLength(0)
    expect(screen.getByRole("button", { name: "Run now" }).textContent).toContain("Run now")
    expect(screen.queryByRole("button", { name: "Set aside" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "More actions" }))
    await user.click(await screen.findByRole("menuitem", { name: "Set aside" }))
    expect(world.moved).toEqual([["abc", "blocked"]])
  })

  test.each(["validated", "done", "cancelled"])("%s, it waits on nobody: no filled button, only …", (column) => {
    const { container } = render(<TicketActions ticket={ticket(column)} card />)
    expect(filled(container)).toHaveLength(0)
    expect(container.querySelectorAll("button")).toHaveLength(1)
    expect(screen.getByRole("button", { name: "More actions" })).toBeTruthy()
  })

  test("given up, it is reopened as a draft from its menu", async () => {
    const user = userEvent.setup()
    render(<TicketActions ticket={ticket("cancelled")} card />)
    await user.click(screen.getByRole("button", { name: "More actions" }))
    await user.click(await screen.findByRole("menuitem", { name: "Reopen" }))
    expect(world.moved).toEqual([["abc", "draft"]])
  })

  test("off the board, the ticket's page keeps its buttons as they were", () => {
    render(<TicketActions ticket={ticket("ready")} />)
    expect(screen.getByRole("button", { name: "Set aside" })).toBeTruthy()
  })
})
