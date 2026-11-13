import * as React from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Goal } from "@/lib/types"

import { GoalCards, GoalPage, NoGoal } from "./goal-cards"

/* A goal's page and the empty list: what deleting one says, and what an empty
 * list offers. */

const world = vi.hoisted(() => ({
  goal: {} as Record<string, unknown>,
  read: { goals: [] as unknown[], configured: true, problem: "" },
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
vi.mock("@/resources/schedules", () => ({ scheduleHref: (id: string) => `/schedules/${id}` }))
vi.mock("@/lib/board-store", () => ({ useBoard: () => ({ columns: [], tickets: [] }) }))
vi.mock("./record-window", () => ({ useOpensOverTheList: () => ({ to: "", onClick: () => {} }) }))

const goal = (url: string): Goal =>
  ({ id: "g1", name: "Launch v1", url, projects: [], tickets: {}, linked: [], priority: null }) as unknown as Goal

beforeEach(() => {
  world.read = { goals: [], configured: true, problem: "" }
})

describe("a goal's page", () => {
  test("offers no link out of the console for a goal", () => {
    world.goal = goal("ponos://page/g1")
    render(<GoalPage />)
    expect(screen.queryByRole("link", { name: /^Open in/ })).toBeNull()
  })

  test("says what deleting a goal does, and that its tickets stay", async () => {
    world.goal = goal("")
    render(<GoalPage />)
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog.textContent).toContain("The goal is deleted.")
    expect(dialog.textContent).toContain("Its tickets stay where they are")
  })
})

describe("the schedules a goal's page lists", () => {
  test("lists those that serve it, each a way to its page, and says a paused one is", () => {
    world.goal = {
      ...goal(""),
      recurrences: [
        { id: "s1", name: "Article de blog", active: true },
        { id: "s2", name: "Revue", active: false },
      ],
    }
    render(<GoalPage />)
    expect(screen.getByRole("link", { name: "Article de blog" }).getAttribute("href")).toBe("/schedules/s1")
    const rows = document.querySelectorAll("[data-goal-schedule]")
    expect(rows).toHaveLength(2)
    expect(rows[1].textContent).toContain("Paused")
  })

  test("draws nothing for a goal no schedule serves", () => {
    world.goal = goal("")
    render(<GoalPage />)
    expect(document.querySelector("[data-slot=goal-schedules]")).toBeNull()
  })
})

describe("the empty list of goals", () => {
  test("says there is no goal, and sends nobody elsewhere", () => {
    world.read = { goals: [], configured: false, problem: "" }
    const { container } = render(<NoGoal />)
    expect(container.textContent).toContain("No goal.")
    expect(container.querySelector("a")).toBeNull()
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
