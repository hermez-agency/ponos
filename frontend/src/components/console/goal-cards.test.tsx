import * as React from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Goal } from "@/lib/types"

import { GoalPage, NoGoal } from "./goal-cards"

/* A goal's page and the empty list, on either board: a board of Markdown files
 * keeps a goal as a file under goals/, so its page has no Notion to open — its
 * address is a file:// one — and its words do not send anyone to Notion. */

const world = vi.hoisted(() => ({
  goal: {} as Record<string, unknown>,
  read: { goals: [] as unknown[], configured: true, storage: "notion", problem: "" },
}))

vi.mock("react-resource-view", async (original) => ({
  ...(await original<typeof import("react-resource-view")>()),
  useCurrentViewResourceContext: () => ({ data: world.goal, fetchData: () => {} }),
  useListViewContext: () => ({ filterContext: { filter: {}, filterIsEmpty: true } }),
  useNavigate: () => () => {},
  useViewLink: () => ({ to: "/tickets/new", onOpen: () => {} }),
  ResourceViewButton: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}))

vi.mock("@/resources/goals", () => ({
  goals: { onChange: { publish: () => {} } },
  goalHref: (id: string) => `/goals/${id}`,
  goalsHref: () => "/goals",
  goalsOnce: () => Promise.resolve([]),
  useGoals: () => world.read,
}))

vi.mock("@/resources/tickets", () => ({
  boardHref: () => "/?view=console/tickets/list",
  ticketHref: (id: string) => `/tickets/${id}`,
  tickets: {},
}))
vi.mock("@/lib/board-store", () => ({ useBoard: () => ({ columns: [], tickets: [] }) }))
vi.mock("./record-window", () => ({ useOpensOverTheList: () => ({ to: "", onClick: () => {} }) }))

const goal = (url: string): Goal =>
  ({ id: "g1", name: "Launch v1", url, projects: [], tickets: {}, linked: [], priority: null }) as unknown as Goal

beforeEach(() => {
  world.read = { goals: [], configured: true, storage: "notion", problem: "" }
})

describe("a goal's page", () => {
  test("opens a Notion goal in Notion", () => {
    world.goal = goal("https://www.notion.so/g1")
    render(<GoalPage />)
    expect(screen.getByRole("link", { name: "Open in Notion" }).getAttribute("href")).toBe("https://www.notion.so/g1")
  })

  test("offers no Notion link for a goal kept as a file", () => {
    world.read.storage = "markdown"
    world.goal = goal("file:///home/me/board/goals/launch-v1.md")
    render(<GoalPage />)
    expect(screen.queryByRole("link", { name: "Open in Notion" })).toBeNull()
  })

  test("says a Markdown goal goes to the board's trash, not Notion's", async () => {
    world.read.storage = "markdown"
    world.goal = goal("file:///home/me/board/goals/launch-v1.md")
    render(<GoalPage />)
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog.textContent).toContain("the board's trash")
    expect(dialog.textContent).not.toContain("Notion")
  })
})

describe("the empty list of goals", () => {
  test("sends a Markdown board to its goals/ folder, not to Notion", () => {
    world.read = { goals: [], configured: false, storage: "markdown", problem: "" }
    const { container } = render(<NoGoal />)
    expect(container.textContent).toContain("goals/")
    expect(container.textContent).not.toContain("Notion")
  })

  test("sends a Notion board to its Goals database", () => {
    world.read = { goals: [], configured: false, storage: "notion", problem: "" }
    const { container } = render(<NoGoal />)
    expect(container.textContent).toContain("Goals database")
  })
})
