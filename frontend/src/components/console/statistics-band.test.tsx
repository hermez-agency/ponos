import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi, type MockInstance } from "vitest"

import type { Board, Statistics } from "@/lib/types"

/* The band at the top of the dashboard, with figures of our own: what is
 * checked is what it asks for and how it draws the answer — the same promises
 * as `e2e/dashboard.spec.ts`, without a server to keep them.
 *
 * The band keeps its period and the figures it read at the module's level, so
 * that a trip to a ticket and back finds them: each test takes a fresh copy of
 * the module, or the second would be drawn from the first one's answer.
 */

let StatisticsBand: typeof import("./statistics-band").StatisticsBand
let statistics: MockInstance<(from: string, to: string, project?: string) => Promise<Statistics>>

/** The local day `back` days before today, as the band asks for it. */
function day(back: number): string {
  const date = new Date()
  date.setDate(date.getDate() - back)
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const subtype = (key: string, label: string) => ({ key, option: label, label, commit: "", changelog: "" })

const BOARD = {
  tickets: [],
  columns: [
    { key: "ready", name: "Ready" },
    { key: "done", name: "Done" },
  ],
  subtypes: [subtype("feature", "Feature"), subtype("bug", "Bug")],
} as unknown as Board

function figures(change: Partial<Statistics> = {}): Statistics {
  return {
    from: day(6),
    to: day(0),
    totals: { created: 9, closed: 4, open: 5, cost: 6.84 },
    days: [
      { day: day(2), created: 4, closed: 1, open: 3, cost: 0 },
      { day: day(1), created: 3, closed: 2, open: 4, cost: 3.42 },
      { day: day(0), created: 2, closed: 1, open: 5, cost: 3.42 },
    ],
    statuses: [
      { key: "ready", count: 3 },
      { key: "done", count: 6 },
    ],
    projects: [
      { name: "Opoil", count: 4 },
      { name: "Website", count: 5 },
    ],
    dated: { history: 3, edited: 1 },
    average: 1.71,
    blocks: { total: 0, weeks: [], causes: [] },
    made: {
      unit: "day",
      buckets: [day(2), day(1), day(0)],
      cells: [
        { bucket: day(2), kind: "code", subtype: "bug", project: "Opoil", count: 3 },
        { bucket: day(2), kind: "code", subtype: "feature", project: "Opoil", count: 1 },
        { bucket: day(1), kind: "code", subtype: "feature", project: "Website", count: 3 },
        { bucket: day(0), kind: "code", subtype: "", project: "Website", count: 2 },
      ],
      before: [{ kind: "code", subtype: "bug", project: "Opoil", count: 2 }],
    },
    ...change,
  }
}

beforeEach(async () => {
  vi.resetModules()
  const { api } = await import("@/lib/api")
  statistics = vi.spyOn(api, "statistics").mockResolvedValue(figures())
  ;(await import("@/lib/board-store")).publishBoard(BOARD)
  StatisticsBand = (await import("./statistics-band")).StatisticsBand
})

/** The band, once its figures are drawn. */
async function drawn(project?: string) {
  render(<StatisticsBand project={project} />)
  const band = screen.getByLabelText("Statistics")
  await within(band).findByText("Activity")
  return band
}

/** One of the four cards, by the label it wears. */
const card = (band: HTMLElement, label: string) =>
  Array.from(band.querySelectorAll("section")).find((tile) => tile.firstElementChild?.textContent === label)!

describe("the period", () => {
  test("opens on the last seven days", async () => {
    const band = await drawn()
    expect(statistics).toHaveBeenCalledWith(day(6), day(0), undefined)
    expect(within(band).getByRole("tab", { name: "7 days" }).getAttribute("aria-selected")).toBe("true")
  })

  test("a period picked is asked for again", async () => {
    const user = userEvent.setup()
    const band = await drawn()
    await user.click(within(band).getByRole("tab", { name: "30 days" }))
    expect(statistics).toHaveBeenLastCalledWith(day(29), day(0), undefined)
    await user.click(within(band).getByRole("tab", { name: "24 h" }))
    expect(statistics).toHaveBeenLastCalledWith(day(1), day(0), undefined)
  })

  test("Custom offers two dates, and a period that ends before it starts is not asked for", async () => {
    const user = userEvent.setup()
    const band = await drawn()
    await user.click(within(band).getByRole("tab", { name: "Custom" }))
    const from = within(band).getByLabelText("From") as HTMLInputElement
    expect(from.value).toBe(day(6))
    fireEvent.change(from, { target: { value: day(10) } })
    await waitFor(() => expect(statistics).toHaveBeenLastCalledWith(day(10), day(0), undefined))
    const asked = statistics.mock.calls.length
    fireEvent.change(from, { target: { value: day(-3) } })
    expect(from.value).toBe(day(-3))
    expect(statistics).toHaveBeenCalledTimes(asked)
  })

  test("a project's band asks for that project alone, and counts its tickets by status", async () => {
    const band = await drawn("Opoil")
    expect(statistics).toHaveBeenCalledWith(day(6), day(0), "Opoil")
    expect(within(band).getByText("Created, by status")).toBeTruthy()
    expect(within(band).queryByText("Created, by project")).toBeNull()
    // What a closed ticket cost it, under what it spent.
    expect(card(band, "Spent").textContent).toContain("per closed ticket")
  })
})

describe("the figures", () => {
  test("four cards, then the activity, what was created, and by project", async () => {
    const band = await drawn()
    expect(card(band, "Open").textContent).toContain("5")
    expect(card(band, "Closed").textContent).toContain("4")
    expect(card(band, "Created").textContent).toContain("9")
    expect(card(band, "Spent").textContent).toContain("$6.84")
    expect(within(band).getByText("Created, by type and sub-type")).toBeTruthy()
    expect(within(band).getByText("Created, by project")).toBeTruthy()
  })

  test("a period with nothing in it says so, rather than drawing empty charts", async () => {
    statistics.mockResolvedValue(figures({ totals: { created: 0, closed: 0, open: 0, cost: 0 } }))
    render(<StatisticsBand />)
    expect(await screen.findByText("No ticket on the board over this period.")).toBeTruthy()
    expect(screen.queryByText("Activity")).toBeNull()
  })

  test("a question that failed says why", async () => {
    statistics.mockRejectedValue(new Error("Notion did not answer"))
    render(<StatisticsBand />)
    expect(await screen.findByText("Notion did not answer")).toBeTruthy()
    expect(screen.queryByText("Counting the tickets…")).toBeNull()
  })
})

describe("folding", () => {
  test("the band folds into one line, and stays folded", async () => {
    const user = userEvent.setup()
    const band = await drawn()
    await user.click(within(band).getByRole("button", { name: /Statistics/ }))
    expect(within(band).queryByText("Activity")).toBeNull()
    expect(within(band).getByText(/5 open · 4 closed · 9 created · \$6\.84 spent/)).toBeTruthy()

    // Drawn again, as after a reload: still folded.
    cleanup()
    render(<StatisticsBand />)
    await waitFor(() => expect(screen.getByText(/5 open · 4 closed/)).toBeTruthy())
    expect(screen.queryByText("Activity")).toBeNull()
  })

  test("the blocks panel is folded behind Show more, and stays as it was left", async () => {
    const user = userEvent.setup()
    const band = await drawn()
    expect(within(band).queryByText("Blocks, by cause and week")).toBeNull()
    await user.click(within(band).getByRole("button", { name: "Show more" }))
    expect(within(band).getByText("Blocks, by cause and week")).toBeTruthy()
    expect(within(band).getByText("No ticket stopped in the period.")).toBeTruthy()
    expect(localStorage.getItem("ponos-statistics-blocks")).toBe("shown")
    await user.click(within(band).getByRole("button", { name: "Show less" }))
    expect(within(band).queryByText("Blocks, by cause and week")).toBeNull()
  })
})

describe("what was created", () => {
  test("a regression rate against the period before, and a table of the projects to pick one from", async () => {
    const user = userEvent.setup()
    const band = await drawn()
    const made = band.querySelector<HTMLElement>('[data-slot="made-chart"]')!
    // A ticket with no sub-type is its own part of the bars.
    expect(within(made).getByText("Unclassified")).toBeTruthy()
    // 3 bugs over 3 bugs and 4 features; the period before was all bugs.
    const rate = made.querySelector('[data-slot="regression-rate"]')!
    expect(rate.textContent).toContain("43 %")
    expect(made.querySelector('[data-trend="down"]')).not.toBeNull()

    expect(made.querySelector('[data-slot="made-projects"]')).toBeNull()
    const more = within(made).getByRole("button", { name: /^See by project \(2\)/ })
    expect(more.getAttribute("aria-expanded")).toBe("false")
    await user.click(more)
    expect(within(made).getByRole("button", { name: "Hide" }).getAttribute("aria-expanded")).toBe("true")
    const first = made.querySelector<HTMLElement>('[data-slot="made-projects"] tbody tr')!
    expect(first.dataset.project).toBe("Opoil")
    await user.click(first)
    expect(rate.textContent).toContain("75 %")
    expect(made.querySelector('[data-slot="made-projects"]')).toBeNull()
  })

  test("filtered by a type that has none, it says which", async () => {
    const user = userEvent.setup()
    const band = await drawn()
    const made = band.querySelector<HTMLElement>('[data-slot="made-chart"]')!
    const type = within(made).getByRole("combobox", { name: "Type" })
    expect(type.textContent).toBe("All types")
    await user.click(type)
    await user.click(await screen.findByRole("option", { name: "Writing" }))
    expect(within(made).getByText("No Writing ticket created in the period.")).toBeTruthy()
  })
})
