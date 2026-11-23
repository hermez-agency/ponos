import { expect, test, type Page } from "@playwright/test"

/* The search over the board and over a project's tickets.
 *
 * What it decides is held by `src/lib/ticket-search.test.ts`; what is held
 * here is what only a page shows: the cards it hides and the columns it does
 * not, the address it writes and reads back, the keys it answers, the line it
 * draws when nothing is left.
 */

test.use({ viewport: { width: 1440, height: 900 } })

const NEWSLETTER = "0000000000000000000000000000beef"

const signIn = (page: Page) =>
  page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])

async function open(page: Page, path = "/") {
  await signIn(page)
  await page.goto(path)
  await expect(page.getByRole("searchbox", { name: "Search tickets" })).toBeVisible()
}

const card = (page: Page, title: string) =>
  page.locator('[data-slot="admin-content"]').getByRole("link", { name: title, exact: true })

async function make(page: Page, title: string, project: string) {
  await signIn(page)
  const response = await page.request.post("/api/tickets", {
    headers: { "X-Ponos": "1" },
    data: { title, body: "", project, ready: true },
  })
  expect(response.ok()).toBeTruthy()
}

test("words and a status combine, the columns stay and count, and the address keeps it all", async ({ page }) => {
  await open(page)
  const field = page.getByRole("searchbox", { name: "Search tickets" })
  await field.fill("TICKET 1")
  await expect(card(page, "Ticket 10")).toBeVisible()
  await expect(card(page, "Ticket 2")).toBeHidden()
  await expect(card(page, "Ticket 1")).toBeVisible()
  // The word is marked where the card says it.
  await expect(card(page, "Ticket 10").locator('[data-slot="search-mark"]').first()).toHaveText("Ticket")

  await page.getByRole("button", { name: /^Status/ }).click()
  await page.getByRole("menuitemcheckbox", { name: /^Draft/ }).click()
  await page.keyboard.press("Escape")
  await expect(page).toHaveURL(/q=TICKET(%20|\+)1/)
  await expect(page).toHaveURL(/status=draft/)
  // A column the search emptied is still there, saying it kept none of its own.
  await expect(card(page, "A long ticket")).toBeHidden()
  await expect(page.getByText(/^0 \/ \d+$/).first()).toBeVisible()

  await page.reload()
  await expect(page.getByRole("searchbox", { name: "Search tickets" })).toHaveValue("TICKET 1")
  await expect(card(page, "Ticket 10")).toBeVisible()
  await expect(card(page, "Ticket 2")).toBeHidden()

  // The table is handed the same search.
  await page.getByRole("tab", { name: "List" }).click()
  // In any order: react-resource-view 2.0 writes `variant` after the search.
  await expect(page).toHaveURL(/variant=table/)
  await expect(page).toHaveURL(/q=TICKET/)
  await expect(card(page, "Ticket 10")).toBeVisible()
  await expect(card(page, "Ticket 2")).toBeHidden()

  // The status is a pill under the bar, taken off by its cross; the words by the field's.
  await page.getByRole("button", { name: "Remove the filter Status: Draft" }).click()
  await page.getByRole("button", { name: "Clear the search" }).click()
  await expect(page).not.toHaveURL(/q=|status=/)
  await expect(card(page, "Ticket 2")).toBeVisible()
})

test("/ goes to the field, Escape empties it, and a search that finds nothing says so", async ({ page }) => {
  await open(page)
  const field = page.getByRole("searchbox", { name: "Search tickets" })
  await page.locator("body").click({ position: { x: 5, y: 400 } })
  await page.keyboard.press("/")
  await expect(field).toBeFocused()
  await page.keyboard.type("nothing is called this")
  await expect(page.getByText("No ticket matches")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(field).toHaveValue("")
  await expect(page.getByText("No ticket matches")).toBeHidden()

  await field.fill("still nothing")
  await page.getByRole("button", { name: "Clear the filters" }).click()
  await expect(field).toHaveValue("")
  await expect(card(page, "Ticket 2")).toBeVisible()
})

test("a project's page searches its own tickets, with no project to pick", async ({ page }) => {
  const stamp = Date.now()
  await make(page, `Newsletter issue ${stamp}`, NEWSLETTER)
  await make(page, `Newsletter archive ${stamp}`, NEWSLETTER)
  await open(page, `/?view=console/projects/read/${NEWSLETTER}`)
  await expect(page.getByRole("button", { name: /^Project/ })).toHaveCount(0)
  await page.getByRole("searchbox", { name: "Search tickets" }).fill(`issue ${stamp}`)
  await expect(card(page, `Newsletter issue ${stamp}`)).toBeVisible()
  await expect(card(page, `Newsletter archive ${stamp}`)).toBeHidden()
  await expect(page).toHaveURL(new RegExp(`projects/read/${NEWSLETTER}.*q=issue`))
})

/* The audit of November 2026 (B1) found ten menus of the same weight in a row,
 * "Other" cut at 1440 px. The project, the status and the priority stay beside
 * the field; the rest is behind "Filters", which counts the ones on, and those
 * are pills under the bar. */
test("the filters fold behind one button that counts them, and the ones on are pills", async ({ page }) => {
  await open(page)
  const filters = page.locator('[data-slot="filters-button"]')
  await expect(page.getByRole("button", { name: /^Status/ })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Priority/ })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Period/ })).toBeHidden()
  await filters.click()
  await expect(filters).toHaveAttribute("aria-expanded", "true")
  await expect(page.getByRole("button", { name: /^Period/ })).toBeVisible()
  // One list: what is beside the field is not in it again.
  await expect(page.getByRole("button", { name: /^Status/ })).toHaveCount(1)

  // The same address as before, read the same way.
  await open(page, "/?q=Ticket&status=draft&since=7d&only=pr")
  await expect(filters).toContainText("3")
  const pills = page.locator('[data-slot="filter-pill"]')
  await expect(pills).toHaveText(["Status: Draft", "Period: Last 7 days", "With a pull request"])
  await page.getByRole("button", { name: "Remove the filter Period: Last 7 days" }).click()
  await expect(page).not.toHaveURL(/since=/)
  await expect(page).toHaveURL(/status=draft/)
  await expect(filters).toContainText("2")

  // "Clear all" takes the filters off, and leaves the words to the field's cross.
  await page.getByRole("button", { name: "Clear all", exact: true }).click()
  await expect(page).not.toHaveURL(/status=|only=/)
  await expect(page).toHaveURL(/q=Ticket/)
  await expect(pills).toHaveCount(0)

  // A single pill has its cross, and no "Clear all".
  await open(page, "/?status=draft")
  await expect(pills).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Clear all", exact: true })).toHaveCount(0)
})

test("the bar fits every width from 1024 to 1920 px, filters on or not", async ({ page }) => {
  for (const width of [1024, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 })
    for (const path of ["/", "/?status=draft,ready&priority=90&since=30d&only=pr,credits&cost=5"]) {
      await open(page, path)
      const bar = page.locator('[data-slot="ticket-search"]')
      await page.locator('[data-slot="filters-button"]').click()
      const outside = await bar.evaluate((element) => {
        const box = element.getBoundingClientRect()
        return Array.from(element.querySelectorAll("button, input, li"))
          .filter((child) => (child as HTMLElement).offsetParent !== null)
          .filter((child) => {
            const own = child.getBoundingClientRect()
            return own.left < box.left - 0.5 || own.right > box.right + 0.5
          })
          .map((child) => child.textContent || child.getAttribute("aria-label") || child.tagName)
      })
      expect(outside, `out of the bar at ${width} px on ${path}`).toEqual([])
      expect(await bar.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    }
  }
})
