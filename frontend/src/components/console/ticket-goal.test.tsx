import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Ticket } from "@/lib/types"

import { TicketGoal } from "./ticket-goal"

/* The goal picker of the ticket window: offered only where the board can point
 * a ticket at a goal — the server says so by giving the goal choices, as it
 * does to the New ticket form. A board without the column draws no picker. */

const world = vi.hoisted(() => ({
  choices: {} as Record<string, { value: string; label: string }[]>,
}))

vi.mock("@/lib/board-store", () => ({
  patchTicket: () => undefined,
  useBoard: () => ({ columns: [], tickets: [], choices: world.choices }),
}))

vi.mock("@/resources/goals", () => ({
  goalHref: (id: string) => `/goal/${id}`,
  goalsOnce: () => Promise.resolve([{ id: "g1", name: "Launch v2" }]),
}))

vi.mock("react-resource-view", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  Link: ({ to, children, ...rest }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}))

const ticket = { id: "abc", title: "A ticket", goal: "", goal_id: "" } as unknown as Ticket

beforeEach(() => {
  world.choices = {}
})

describe("the goal picker of a ticket", () => {
  test("is offered where the board has a goal column", async () => {
    world.choices = { goal: [{ value: "g1", label: "Launch v2" }] }
    render(<TicketGoal ticket={ticket} />)
    expect(await screen.findByRole("combobox", { name: "Change the goal" })).toBeTruthy()
  })

  test("is not drawn on a board without the goal column, goals or not", async () => {
    const { container } = render(<TicketGoal ticket={ticket} />)
    // The goals are read once the component is drawn: wait for them.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(container.innerHTML).toBe("")
  })
})
