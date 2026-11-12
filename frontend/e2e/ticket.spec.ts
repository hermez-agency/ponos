import { expect, test, type Page } from "@playwright/test"

/* Opening a ticket from the board draws it at once, and reads its page once.
 *
 * The page used to stay empty until the server had read the whole ticket —
 * one to three seconds — while the board already held its title, its
 * column and its project; and the same read went out two or three times. The
 * read is slowed down here on purpose, so that "at once" means before it.
 */

const LONG = "000000000000000000000000000abcde"
const READ = new RegExp(`/api/tickets/${LONG}$`)

async function counted(page: Page) {
  const reads: string[] = []
  await page.route(READ, async (route) => {
    reads.push(route.request().url())
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  return reads
}

const header = (page: Page) => page.locator('[data-slot="admin-header"] h2')
const window_ = (page: Page) => page.getByRole("dialog")

test.use({ viewport: { width: 1440, height: 900 } })

test("a ticket opened from the board is drawn before its brief is read, and read once", async ({ page }) => {
  const reads = await counted(page)
  await page.goto("/?view=console/tickets/list/board")
  await page.getByRole("link", { name: "A long ticket" }).click()

  // What the card knew, while the brief is still on its way.
  await expect(window_(page).locator('[data-slot="dialog-title"]')).toHaveText("A long ticket", { timeout: 1000 })
  await expect(page.getByText("no project — a document")).toBeVisible({ timeout: 1000 })
  await expect(page.getByText("Part 40")).not.toBeAttached()

  await expect(page.getByText("Part 40")).toBeAttached()
  // The stream moves the board meanwhile; the page does not read it again.
  await page.waitForTimeout(1500)
  expect(reads).toHaveLength(1)

  // Back to the board and in again: a new opening, a new read.
  await page.keyboard.press("Escape")
  await expect(window_(page)).not.toBeAttached()
  await page.getByRole("link", { name: "A long ticket" }).click()
  await expect(page.getByText("Part 40")).toBeAttached()
  expect(reads).toHaveLength(2)
})

test("a ticket opened by its address, before the board is there, is read once too", async ({ page }) => {
  const reads = await counted(page)
  await page.goto(`/?view=console/tickets/read/${LONG}`)
  await expect(header(page)).toHaveText("A long ticket")
  await expect(page.getByText("Part 40")).toBeAttached()
  await page.waitForTimeout(1500)
  expect(reads).toHaveLength(1)
})

test("a ticket's page says its type, model and cost under its mission, and the others are tabs", async ({ page }) => {
  const reads = await counted(page)
  await page.goto(`/?view=console/tickets/read/${LONG}`)
  await expect(page.getByText("Part 40")).toBeAttached()

  // Always there, even before anything ran: what it is, on what, for how much.
  const summary = page.locator('[data-slot="ticket-summary"]')
  await expect(summary.getByText("Ticket", { exact: true })).toBeVisible()

  // A ticket neither running nor waiting opens on its mission — its result, once it has one.
  const tabs = page.getByRole("tablist")
  await expect(tabs.getByRole("tab")).toHaveText(["Mission", "Discussion", "Live", "Journal"])
  await expect(tabs.getByRole("tab", { name: "Mission" })).toHaveAttribute("aria-selected", "true")
  await expect(page.getByRole("tabpanel")).toContainText("Part 40")

  // From the keyboard, as a tab list is: the arrows move from one to the next.
  await tabs.getByRole("tab", { name: "Mission" }).focus()
  await page.keyboard.press("ArrowRight")
  await expect(tabs.getByRole("tab", { name: "Discussion" })).toBeFocused()
  await page.keyboard.press("ArrowRight")
  const live = tabs.getByRole("tab", { name: "Live" })
  await expect(live).toHaveAttribute("aria-selected", "true")
  await expect(page.getByText("No journal is left for this ticket", { exact: false })).toBeVisible()
  await expect(page.getByText("Part 40")).not.toBeAttached()

  // The tab is in the address — a reload comes back to it — and changing it
  // reads nothing again.
  await expect(page).toHaveURL(/[?&]tab=live$/)
  await page.waitForTimeout(500)
  expect(reads).toHaveLength(1)
  await page.reload()
  await expect(page.getByRole("tab", { name: "Live" })).toHaveAttribute("aria-selected", "true")
  await expect(page.getByText("No journal is left for this ticket", { exact: false })).toBeVisible()
})

test("a ticket with sessions says the model the last one announced, as provider/model", async ({ page }) => {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  // A question waits on this one, so it opens on its discussion: the facts are the brief's.
  await page.goto("/?view=console/tickets/read/00000000000000000000000000000a5c&tab=brief")

  // The column is empty: the model is the last session's own word, said short
  // and still a default, with the full identifier a hover away.
  const model = page.getByTitle("claude-opus-4-1-20250805")
  await expect(model).toHaveText("opus · default")
})

test("a ticket that waits on an answer shows the 15 minutes it worked and why the clock is stopped", async ({ page }) => {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/?view=console/tickets/read/00000000000000000000000000000a5c")
  await page.getByRole("tab", { name: "Journal" }).click()
  const time = page.locator('[data-slot="ticket-time"]')
  // Ten minutes, an hour of waiting, five more: the hour is not in it.
  await expect(time).toHaveText("15 min")
  await expect(time).toHaveAttribute("title", "On hold: waiting for your answer")

  await time.hover()
  const detail = page.locator('[data-slot="popover-content"]')
  await expect(detail.getByText("Working time")).toBeVisible()
  await expect(detail.getByText("Time on hold")).toBeVisible()
  await expect(detail.getByText("Sessions")).toBeVisible()
  await page.screenshot({ path: "/tmp/ponos-brief-time.png" })

  // On the board, the same work wears the card, quietly.
  await page.keyboard.press("Escape")
  await page.goto("/?view=console/tickets/list/board")
  await expect(page.locator('[data-slot="ticket-card-time"]').first()).toHaveText("15 min")
})
