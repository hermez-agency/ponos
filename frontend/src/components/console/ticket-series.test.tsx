import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import { TicketSeries } from "./ticket-series"

/* The series over the drafts: Ready sends the ticket to ready, Abandon to
 * cancelled, Skip leaves it a draft, and the last choice can be taken back.
 * Around it only what it reads: the address, the board, the server. */

const world = vi.hoisted(() => ({
  searchStr: "?series=draft",
  setStatus: vi.fn((..._args: unknown[]) => Promise.resolve({})),
  patch: vi.fn((..._args: unknown[]) => {}),
}))

vi.mock("@tanstack/react-router", async (original) => ({
  ...(await original<typeof import("@tanstack/react-router")>()),
  useLocation: () => ({ pathname: "/", searchStr: world.searchStr }),
}))
vi.mock("react-resource-view", async (original) => ({
  ...(await original<typeof import("react-resource-view")>()),
  useNavigate: () => () => {},
}))
vi.mock("@/components/console/robot", () => ({ Robot: () => null }))
vi.mock("@/components/console/project-picture", () => ({ ProjectThumb: () => null }))

const draft = (id: string, title: string) => ({
  id,
  short: id,
  title,
  column: "draft",
  status: "Draft",
  project: "ponos",
  priority: 50,
  created: "2026-10-01T10:00:00Z",
})

vi.mock("@/lib/board-store", () => ({
  useBoard: () => ({
    columns: [
      { key: "draft", name: "Draft" },
      { key: "ready", name: "Ready" },
      { key: "cancelled", name: "Cancelled" },
    ],
    tickets: [draft("a", "First draft"), draft("b", "Second draft")],
  }),
  titleOf: (ticket: { title: string }) => ticket.title,
  patchTicket: (...args: unknown[]) => world.patch(...args),
}))

vi.mock("@/lib/api", () => ({
  api: {
    ticket: () => Promise.resolve({ content: "The **body** of the draft" }),
    setStatus: (...args: unknown[]) => world.setStatus(...args),
  },
  why: (error: unknown) => String(error),
}))

beforeEach(() => {
  world.setStatus.mockClear()
  world.patch.mockClear()
})

describe("the series of drafts", () => {
  test("opens on the first draft, with its body and its count", async () => {
    render(<TicketSeries />)
    expect(await screen.findByRole("heading", { name: "First draft" })).toBeTruthy()
    expect(await screen.findByText("body")).toBeTruthy()
    expect(document.querySelector('[data-slot="series-position"]')?.textContent).toContain("1 / 2")
  })

  test("Ready moves it to ready, Abandon to cancelled", async () => {
    const user = userEvent.setup()
    render(<TicketSeries />)
    await screen.findByRole("heading", { name: "First draft" })
    await user.click(document.querySelector<HTMLElement>('[data-move="ready"]')!)
    await waitFor(() => expect(world.setStatus).toHaveBeenCalledWith("a", "ready", "Draft"))
    await screen.findByRole("heading", { name: "Second draft" }, { timeout: 3000 })
    await user.click(document.querySelector<HTMLElement>('[data-move="cancelled"]')!)
    await waitFor(() => expect(world.setStatus).toHaveBeenCalledWith("b", "cancelled", "Draft"))
  })

  test("Skip leaves it a draft and goes to the next", async () => {
    const user = userEvent.setup()
    render(<TicketSeries />)
    await screen.findByRole("heading", { name: "First draft" })
    await user.click(document.querySelector<HTMLElement>('[data-slot="series-skip"]')!)
    expect(await screen.findByRole("heading", { name: "Second draft" })).toBeTruthy()
    expect(world.setStatus).not.toHaveBeenCalled()
  })

  test("the last choice can be taken back", async () => {
    const user = userEvent.setup()
    render(<TicketSeries />)
    await screen.findByRole("heading", { name: "First draft" })
    await user.click(document.querySelector<HTMLElement>('[data-move="ready"]')!)
    await user.click(await screen.findByRole("button", { name: "Undo" }))
    await waitFor(() => expect(world.setStatus).toHaveBeenLastCalledWith("a", "draft", "Ready"))
  })

  test("the R and A keys decide", async () => {
    const user = userEvent.setup()
    render(<TicketSeries />)
    await screen.findByRole("heading", { name: "First draft" })
    await screen.findByText("body")
    await user.keyboard("a")
    await waitFor(() => expect(world.setStatus).toHaveBeenCalledWith("a", "cancelled", "Draft"))
  })
})
