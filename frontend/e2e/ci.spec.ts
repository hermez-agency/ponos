import { expect, test, type Page } from "@playwright/test"

/* The state of a review's checks, on its card and in its window.
 *
 * `e2e/console.py` writes four pull requests in review and what the runner last
 * read of their checks: one red, one running, one green, and one with no check
 * at all, which must say nothing — never a green nobody earned.
 */

const RED = "00000000000000000000000000de1c01"
const RUNNING = "00000000000000000000000000c1c102"
const GREEN = "00000000000000000000000000c1c103"
const NONE = "00000000000000000000000000c1c104"

async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const badge = (page: Page, id: string) =>
  page.locator(`[data-ticket-card="${id}"] [data-slot="ticket-ci"]`)

test("a card in review wears the state of its checks, and none without CI", async ({ page }) => {
  await open(page)
  await expect(badge(page, RED)).toHaveAttribute("data-state", "failed")
  await expect(badge(page, RUNNING)).toHaveAttribute("data-state", "pending")
  await expect(badge(page, GREEN)).toHaveAttribute("data-state", "passed")
  await expect(page.locator(`[data-ticket-card="${NONE}"]`)).toBeVisible()
  await expect(badge(page, NONE)).toHaveCount(0)
  for (const [id, name] of [[RED, "failed"], [RUNNING, "pending"], [GREEN, "passed"]]) {
    await page.locator(`[data-ticket-card="${id}"]`).screenshot({ path: `test-results/ci-${name}.png` })
  }
})

test("the window lists each check and links to GitHub's page", async ({ page }) => {
  await open(page, `/?view=console/tickets/read/${RED}`)
  const detail = page.locator('[data-slot="ticket-ci"]')
  await expect(detail).toHaveAttribute("data-state", "failed")
  await expect(detail.locator("li")).toHaveCount(3)
  await expect(detail.locator("li").nth(1)).toHaveAttribute("data-state", "failed")
  await expect(detail.getByRole("link", { name: "Checks on GitHub" })).toHaveAttribute(
    "href",
    "https://github.com/example/site/pull/3073/checks"
  )
})

test("the list of checks is folded on a green CI, opens by keyboard and the choice is kept", async ({ page }) => {
  await open(page, `/?view=console/tickets/read/${GREEN}`)
  const detail = page.locator('[data-slot="ticket-ci"]')
  const toggle = detail.getByRole("button", { expanded: false })
  await expect(toggle).toContainText(/\d+\/\d+/)
  await expect(detail.locator("li")).toHaveCount(0)
  await expect(detail.getByRole("link", { name: "Checks on GitHub" })).toBeVisible()
  await detail.screenshot({ path: "test-results/ci-folded.png" })
  await toggle.focus()
  await page.keyboard.press("Enter")
  await expect(detail.getByRole("button", { expanded: true })).toBeVisible()
  await expect(detail.locator("li").first()).toBeVisible()
  await detail.screenshot({ path: "test-results/ci-unfolded.png" })
  // One choice for every ticket: it is still open on another, and after a reload.
  await page.reload()
  await expect(detail.locator("li").first()).toBeVisible()
  await detail.getByRole("button", { expanded: true }).click()
  await expect(detail.locator("li")).toHaveCount(0)
})

test("a failed CI is open by default, and names what failed once folded", async ({ page }) => {
  await open(page, `/?view=console/tickets/read/${RED}`)
  const detail = page.locator('[data-slot="ticket-ci"]')
  await expect(detail.locator("li")).toHaveCount(3)
  await detail.screenshot({ path: "test-results/ci-failed-open.png" })
  await detail.getByRole("button", { expanded: true }).click()
  await expect(detail.locator("li")).toHaveCount(0)
  await expect(detail.locator('[data-slot="ticket-ci-failing"]')).toBeVisible()
  await detail.screenshot({ path: "test-results/ci-failed-folded.png" })
})
