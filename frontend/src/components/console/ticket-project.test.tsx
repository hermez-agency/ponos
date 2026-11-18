import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { Ticket } from "@/lib/types"

import { TicketProjectChoice } from "./ticket-project"

/* A ticket stopped on its project is moved to another from its page, and run
 * again in the same gesture: the projects offered, the one it is stuck on left
 * out — and, for a code ticket of « Unknown », only those with a repository. */

const world = vi.hoisted(() => ({
  asked: [] as [string, string, boolean][],
  projects: [
    { id: "u", name: "Unknown", kind: "document", builtin: true },
    { id: "site", name: "Website", kind: "code" },
    { id: "news", name: "Newsletter", kind: "document" },
  ],
}))

vi.mock("@/lib/api", () => ({
  api: {
    projects: () => Promise.resolve({ projects: world.projects }),
    setTicketProject: (ticket: string, project: string, ready: boolean) => {
      world.asked.push([ticket, project, ready])
      return Promise.resolve({ id: ticket, project, project_name: "", status: "ready" })
    },
  },
  why: (error: unknown) => String(error),
}))

vi.mock("@/lib/board-store", () => ({ patchTicket: () => undefined }))
vi.mock("sonner", () => ({ toast: { success: () => undefined, error: () => undefined } }))

const stopped = (code: string, project = "u") =>
  ({
    id: "abc",
    title: "A ticket",
    column: "blocked",
    project_id: project,
    block: { code, family: "access", who: "user", action: "retry", policy: "ask", label: {}, help: {} },
  }) as unknown as Ticket

beforeEach(() => {
  world.asked = []
})

describe("the project of a ticket stopped on it", () => {
  test("is not offered for any other stop", async () => {
    const { container } = render(<TicketProjectChoice ticket={stopped("session.question")} />)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(container.innerHTML).toBe("")
  })

  test("is chosen among the projects, and the ticket runs again", async () => {
    render(<TicketProjectChoice ticket={stopped("project.no-repo", "site")} />)
    const run = await screen.findByRole("button", { name: "Run it again" })
    expect((run as HTMLButtonElement).disabled).toBe(true)
    await userEvent.click(screen.getByRole("combobox", { name: "Choose a project" }))
    const offered = (await screen.findAllByRole("option")).map((option) => option.textContent)
    expect(offered).toEqual(["Unknown", "Newsletter"])
    await userEvent.click(screen.getByRole("option", { name: "Newsletter" }))
    await userEvent.click(run)
    await waitFor(() => expect(world.asked).toEqual([["abc", "news", true]]))
  })

  test("offers a code ticket of Unknown only the projects that have a repository", async () => {
    render(<TicketProjectChoice ticket={stopped("project.which-repo")} />)
    await userEvent.click(await screen.findByRole("combobox", { name: "Choose a project" }))
    const offered = (await screen.findAllByRole("option")).map((option) => option.textContent)
    expect(offered).toEqual(["Website"])
  })
})
