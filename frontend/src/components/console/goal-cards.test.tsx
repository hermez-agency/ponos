import * as React from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Goal } from "@/lib/types"

import { GoalCards, GoalPage, NoGoal } from "./goal-cards"

/* A goal's page and the empty list, with or without a Notion behind the board:
 * without one a goal has no Notion page to open, and its words do not send
 * anyone to Notion. */

const world = vi.hoisted(() => ({
  goal: {} as Record<string, unknown>,
  read: { goals: [] as unknown[], configured: true, notion: true, problem: "" },
}))

vi.mock("react-resource-view", async (original) => ({
  ...(await original<typeof import("react-resource-view")>()),
  useCurrentViewResourceContext: () => ({ data: world.goal, fetchData: () => {} }),
  useListViewContext: () => ({ filterContext: { filter: {}, filterIsEmpty: true } }),
  useNavigate: () => () => {},
  useViewLink: ({ resource, action, id }: { resource: { name: string }; action: string; id?: string }) => ({
    to: `/${resource.name}/${action}${id ? `/${id}` : ""}?view=console`,
    onOpen: () => {},
  }),
  ListPagination: () => null,
  ResourceViewButton: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}))

vi.mock("@/resources/goals", () => ({
  ON_TICKETS: "goal-field=tickets",
  goals: { name: "goals", onChange: { publish: () => {} } },
  goalHref: (id: string) => `/goals/${id}`,
  goalsHref: () => "/goals",
  goalsOnce: () => Promise.resolve([]),
  useGoals: () => world.read,
}))

vi.mock("@/resources/tickets", () => ({
  boardHref: () => "/?view=console/tickets/list",
  ticketHref: (id: string) => `/tickets/${id}`,
  tickets: { name: "tickets" },
}))
vi.mock("@/lib/board-store", () => ({ useBoard: () => ({ columns: [], tickets: [] }) }))
vi.mock("./record-window", () => ({ useOpensOverTheList: () => ({ to: "", onClick: () => {} }) }))

const goal = (url: string): Goal =>
  ({ id: "g1", name: "Launch v1", url, projects: [], tickets: {}, linked: [], priority: null }) as unknown as Goal

beforeEach(() => {
  world.read = { goals: [], configured: true, notion: true, problem: "" }
})

describe("a goal's page", () => {
  test("opens a Notion goal in Notion", () => {
    world.goal = goal("https://www.notion.so/g1")
    render(<GoalPage />)
    expect(screen.getByRole("link", { name: "Open in Notion" }).getAttribute("href")).toBe("https://www.notion.so/g1")
  })

  test("offers no Notion link for a goal on a board without Notion", () => {
    world.read.notion = false
    world.goal = goal("")
    render(<GoalPage />)
    expect(screen.queryByRole("link", { name: "Open in Notion" })).toBeNull()
  })

  test("says a goal without Notion is not sent to Notion's trash", async () => {
    world.read.notion = false
    world.goal = goal("")
    render(<GoalPage />)
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog.textContent).toContain("The goal is deleted.")
    expect(dialog.textContent).not.toContain("Notion")
  })
})

describe("the empty list of goals", () => {
  test("does not send a board without Notion to Notion", () => {
    world.read = { goals: [], configured: false, notion: false, problem: "" }
    const { container } = render(<NoGoal />)
    expect(container.textContent).not.toContain("Notion")
  })

  test("sends a Notion board to its Goals database", () => {
    world.read = { goals: [], configured: false, notion: true, problem: "" }
    const { container } = render(<NoGoal />)
    expect(container.textContent).toContain("Goals database")
  })
})

describe("a goal's card", () => {
  const card = (tickets: Record<string, number>, projects: string[] = []) =>
    render(<GoalCards rows={[{ data: { ...goal(""), projects, tickets } }] as never} />).container

  test("says a goal no ticket serves has none, and offers to tie some or write one", () => {
    const drawn = card({}, ["Trouver mission", "Leadz Ninja"])
    expect(drawn.textContent).toContain("No ticket tied yet")
    expect(drawn.textContent).not.toContain("0 of 0")
    expect(screen.queryByRole("progressbar")).toBeNull()
    const tie = screen.getByRole("link", { name: "Tie tickets" }).getAttribute("href") ?? ""
    expect(tie).toContain("/goals/update/g1")
    expect(tie).toContain("goal-field=tickets")
    const write = screen.getByRole("link", { name: "New ticket for this goal" }).getAttribute("href")
    expect(write).toMatch(/^\/tickets\/create/)
  })

  test("draws the count and the bar of a goal tickets serve", () => {
    const drawn = card({ done: 2, ready: 1 })
    expect(screen.getByRole("progressbar").getAttribute("aria-label")).toBe("2 of 3 tickets done")
    expect(drawn.textContent).not.toContain("No ticket tied yet")
    expect(screen.queryByRole("link", { name: "Tie tickets" })).toBeNull()
  })

  test("names the projects the goal is for", () => {
    card({ done: 1 }, ["Trouver mission", "Leadz Ninja"])
    expect(document.querySelector("[data-slot=goal-projects]")?.textContent).toBe("Trouver mission, Leadz Ninja")
  })
})
