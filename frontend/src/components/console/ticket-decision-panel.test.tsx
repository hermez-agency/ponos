import { render, screen } from "@testing-library/react"
import { describe, expect, test, vi } from "vitest"

import type { Decision, Ticket } from "@/lib/types"

import { TicketDecision } from "./ticket-decision-panel"

/* The Decide tab of a ticket in review, read on a phone without GitHub: each
 * job of its CI and each file it touches, with its lines, above the choices.
 * Around it only what it reads: the board and the server. */

const world = vi.hoisted(() => ({ decision: {} as Record<string, unknown> }))

vi.mock("@/lib/board-store", () => ({
  useBoard: () => ({ columns: [], tickets: [] }),
  titleOf: (ticket: { title: string }) => ticket.title,
}))

vi.mock("@/lib/api", () => ({
  api: { decision: () => Promise.resolve(world.decision) },
  why: (error: unknown) => String(error),
}))

const url = "https://github.com/a/b/pull/7"
const reviewed = (extra: Partial<Decision>) => ({
  id: "abc",
  column: "review",
  summary: "Sorts the list.",
  pull_request: url,
  checks: { state: "passed", link: `${url}/checks`, listed: [] },
  caveats: [],
  solutions: [{ key: "validate", column: "validated", needs: "", text: "", number: 0, label: "validate" }],
  ...extra,
})
const ticket = { id: "abc", title: "A list", column: "review" } as unknown as Ticket

describe("the Decide tab of a ticket in review", () => {
  test("lists each job of its CI, by its state, a link to the job's page", async () => {
    world.decision = reviewed({
      checks: {
        state: "failed",
        link: "",
        listed: [
          { name: "core", bucket: "pass", link: `${url}/checks?1` },
          { name: "frontend", bucket: "fail", link: "" },
          { name: "image", bucket: "pending", link: "" },
        ],
      },
    })
    render(<TicketDecision ticket={ticket} onDone={() => {}} />)
    const jobs = await screen.findAllByRole("listitem")
    const section = document.querySelector('[data-slot="decision-checks"]')!
    expect(jobs.length).toBeGreaterThan(0)
    expect([...section.querySelectorAll("li")].map((one) => one.dataset.state)).toEqual([
      "passed",
      "failed",
      "pending",
    ])
    expect(screen.getByRole("link", { name: "core" }).getAttribute("href")).toBe(`${url}/checks?1`)
  })

  test("lists the files it touches with their lines, the first ones and how many more", async () => {
    const files = Array.from({ length: 14 }, (_, index) => ({
      path: `src/file-${index}.ts`,
      additions: 2,
      deletions: 1,
    }))
    world.decision = reviewed({ files })
    render(<TicketDecision ticket={ticket} onDone={() => {}} />)
    await screen.findByText("Files changed")
    const section = document.querySelector('[data-slot="decision-files"]')!
    expect(section.querySelectorAll("li")).toHaveLength(12)
    expect(section.textContent).toContain("14 · +28 −14")
    expect(screen.getByRole("link", { name: "and 2 more" }).getAttribute("href")).toBe(`${url}/files`)
  })

  test("says nothing of files or jobs GitHub did not give", async () => {
    world.decision = reviewed({})
    render(<TicketDecision ticket={ticket} onDone={() => {}} />)
    await screen.findByText("Sorts the list.")
    expect(document.querySelector('[data-slot="decision-files"]')).toBeNull()
    expect(document.querySelector('[data-slot="decision-checks"]')).toBeNull()
  })
})
