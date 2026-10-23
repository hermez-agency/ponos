import { expect, test, type Page } from "@playwright/test"

/* The schedules in two columns, as the projects are: the list on the left, the
 * schedule picked on the right — its tickets, what they cost, its passes and its
 * settings.
 *
 * What a schedule made is answered by the test for "Weekly digest": a ticket
 * more on the shared board would be one more card for every other spec to
 * count. "Test email" is read from the server as it is, a schedule that has
 * made nothing yet. The ticket listed is one the board has, so that a click
 * opens its window.
 */

const LIST = "/?view=console/schedules/list"
const DIGEST = "00000000000000000000000000005ed2"
const FINISHED = "0000000000000000000000000000d0e0"

const ACTIVITY = {
  tickets: [
    {
      id: FINISHED,
      short: "d0e0",
      title: "Weekly digest — 2026-10-12",
      url: "",
      status: "Done",
      column: "done",
      created: "2026-10-12T07:00:00Z",
      cost: 1.25,
      duration: 30,
      pull_request: "https://github.com/example/website/pull/7",
      linked: "recorded",
    },
    {
      id: "0000000000000000000000000000beef",
      short: "beef",
      title: "Weekly digest — 2026-10-05",
      url: "",
      status: "Failed",
      column: "failed",
      created: "2026-10-05T07:00:00Z",
      cost: 0.75,
      duration: 10,
      pull_request: "",
      linked: "title",
    },
  ],
  runs: [
    { at: "2026-10-19T07:00:00+00:00", outcome: "skipped", ticket: "", title: "", reason: "open", column: "", inferred: false },
    { at: "2026-10-12T07:00:00+00:00", outcome: "born", ticket: FINISHED, title: "Weekly digest — 2026-10-12", reason: "", column: "done", inferred: false },
    { at: "2026-10-05T07:00:00Z", outcome: "born", ticket: "0000000000000000000000000000beef", title: "Weekly digest — 2026-10-05", reason: "", column: "failed", inferred: true },
  ],
  statuses: [
    { key: "done", count: 1 },
    { key: "failed", count: 1 },
  ],
  totals: { tickets: 2, cost: 2, average_cost: 1, average_duration: 20, success: 0.5 },
  weeks: [
    { week: "2026-10-05", tickets: 1, done: 0, open: 0, cost: 0.75 },
    { week: "2026-10-12", tickets: 1, done: 1, open: 0, cost: 1.25 },
  ],
  since: "2026-10-12T07:00:00+00:00",
  matched: 1,
}

async function open(page: Page, url = LIST) {
  await page.route(`**/api/schedules/${DIGEST}/activity`, (route) => route.fulfill({ json: ACTIVITY }))
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(url)
  await expect(item(page, "Weekly digest")).toBeVisible()
}

const item = (page: Page, name: string) => page.locator("[data-schedule-item]", { hasText: name })
const panel = (page: Page) => page.locator("[data-schedule-panel]")

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("a schedule picked shows its tickets, its cost and its figures beside the list, in the address", async ({ page }) => {
    await open(page)
    await expect(panel(page)).toHaveCount(0)
    await expect(page.getByText("Pick a schedule")).toBeVisible()
    const before = await page.evaluate(() => window.scrollY)

    await item(page, "Weekly digest").click()
    await expect(item(page, "Weekly digest")).toHaveAttribute("aria-pressed", "true")
    await expect(panel(page).getByRole("heading", { name: "Weekly digest" })).toBeVisible()
    const list = (await item(page, "Weekly digest").boundingBox())!
    const beside = (await panel(page).boundingBox())!
    expect(list.x + list.width).toBeLessThanOrEqual(beside.x)
    // Picking is not scrolling.
    expect(await page.evaluate(() => window.scrollY)).toBe(before)

    const figures = panel(page).locator("[data-schedule-figures]")
    await expect(figures).toContainText("$2.00")
    await expect(figures).toContainText("50 %")
    await expect(figures).toContainText("20 min")
    await expect(figures.locator("[data-schedule-statuses]")).toContainText("Done 1")
    await expect(figures.locator("[data-schedule-statuses]")).toContainText("Failed 1")
    // The tabs sit under the figures.
    const tabs = (await panel(page).getByRole("tab", { name: "Tickets" }).boundingBox())!
    expect(tabs.y).toBeGreaterThan((await figures.boundingBox())!.y)

    const rows = panel(page).locator("[data-schedule-ticket]")
    await expect(rows).toHaveCount(2)
    await expect(rows.first()).toContainText("Weekly digest — 2026-10-12")
    await expect(rows.first().getByRole("link", { name: "Pull request" })).toHaveAttribute("href", /pull\/7/)
    await expect(panel(page)).toContainText("recognised by its title")

    await expect(page).toHaveURL(new RegExp(`schedule=${DIGEST}`))
    await page.reload()
    await expect(panel(page).getByRole("heading", { name: "Weekly digest" })).toBeVisible()

    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, "no sideways scroll").toBeLessThanOrEqual(1440)
  })

  test("a ticket opens in its window, the schedule still picked behind it", async ({ page }) => {
    await open(page, `${LIST}&schedule=${DIGEST}`)
    await panel(page).getByRole("link", { name: "Weekly digest — 2026-10-12" }).click()
    await expect(page.getByRole("dialog")).toContainText("A finished ticket")
    await expect(page).toHaveURL(new RegExp(`schedule=${DIGEST}`))
    await page.keyboard.press("Escape")
    await expect(page.getByRole("dialog")).not.toBeAttached()
    await expect(panel(page).getByRole("heading", { name: "Weekly digest" })).toBeVisible()
  })

  test("the runs say what each pass made or why it made none, and the settings are written on the spot", async ({ page }) => {
    await open(page, `${LIST}&schedule=${DIGEST}`)
    await panel(page).getByRole("tab", { name: "Runs" }).click()
    await expect(page).toHaveURL(/tab=runs/)
    const runs = panel(page).locator("[data-schedule-run]")
    await expect(runs).toHaveCount(3)
    await expect(runs.first()).toContainText("Skipped")
    await expect(runs.first()).toContainText("still open")
    await expect(runs.last()).toContainText("said from the ticket")

    await panel(page).getByRole("tab", { name: "Settings" }).click()
    const settings = panel(page).locator("[data-schedule-settings]")
    await expect(settings.getByText("What Ponos must do every time").first()).toBeVisible()
    await expect(settings.getByText("Project", { exact: true }).first()).toBeVisible()
    // Saved where it is: the columns it is written in, its project with them,
    // and the schedule still picked. The write is answered by the test.
    const sent: Record<string, unknown>[] = []
    await page.route(new RegExp(`/api/schedules/${DIGEST}$`), async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      sent.push(route.request().postDataJSON())
      await route.fulfill({ json: { id: DIGEST } })
    })
    await settings.getByRole("button", { name: "Save" }).click()
    await expect.poll(() => sent.length).toBe(1)
    expect(sent[0]).toMatchObject({ name: "Weekly digest", cadence: "Hourly", project: "" })
    await expect(page).toHaveURL(new RegExp(`schedule=${DIGEST}`))
    await expect(panel(page).getByRole("heading", { name: "Weekly digest" })).toBeVisible()
  })

  test("a schedule that made nothing says so, from the server itself", async ({ page }) => {
    await open(page)
    await item(page, "Test email").click()
    await expect(panel(page).getByText("No ticket yet")).toBeVisible()
    await expect(panel(page).getByRole("button", { name: "Run now" })).toBeVisible()
    await expect(panel(page).getByRole("link", { name: "Edit" })).toBeVisible()
    await expect(panel(page).getByRole("switch")).toBeVisible()
  })

  test("the calendar is still a tab away", async ({ page }) => {
    await open(page)
    await page.getByRole("tab", { name: "Calendar" }).click()
    await expect(page).toHaveURL(/variant=calendar/)
    await expect(page.locator("[data-schedule-item]")).toHaveCount(0)
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("the list, then the schedule on the whole screen, and back", async ({ page }) => {
    await open(page)
    await expect(page.locator("[data-schedules-aside]")).toHaveCount(0)
    await item(page, "Weekly digest").click()
    const screen = page.locator("[data-schedule-screen]")
    await expect(screen.getByRole("heading", { name: "Weekly digest" })).toBeVisible()
    const box = (await screen.boundingBox())!
    expect([box.x, box.y, box.width]).toEqual([0, 0, 390])
    await expect(screen.locator("[data-schedule-figures]")).toContainText("$2.00")
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0)

    await screen.getByRole("button", { name: "Schedules" }).click()
    await expect(screen).toHaveCount(0)
    await expect(page).not.toHaveURL(/schedule=/)
    await expect(item(page, "Weekly digest")).toBeVisible()
  })
})
