import { expect, test, type Page } from "@playwright/test"

/* The Projects page in two columns: the list on the left, the global context or
 * the project picked on the right.
 *
 * What is tested is the way a person goes: a project picked fills the panel
 * with its page — the same one its address opens, tabs and actions included —
 * and the context makes way for it, a link back rather than a second header
 * the same size; the tab picked there is kept from one project to the next,
 * and the page alone is a link away, on that tab; and on a phone, where there
 * is no room for a panel, a project picked is its page.
 */

const LIST = "/?view=console/projects/list"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await expect(page.locator("[data-project-item]", { hasText: "Website" })).toBeVisible()
}

const item = (page: Page, name: string) => page.locator("[data-project-item]", { hasText: name })
const panel = (page: Page) => page.locator("[data-project-panel]")
const tab = (scope: Page | ReturnType<typeof panel>, name: string) => scope.getByRole("tab", { name, exact: true })

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("the list is on the left, the context or the project picked on the right", async ({ page }) => {
    await open(page)
    const context = (await page.locator('[data-slot="context-block"]').boundingBox())!
    const first = (await item(page, "Website").boundingBox())!
    expect(first.x + first.width).toBeLessThanOrEqual(context.x)
    await expect(panel(page)).toHaveCount(0)

    await item(page, "Website").click()
    await expect(item(page, "Website")).toHaveAttribute("aria-pressed", "true")
    await expect(panel(page).getByRole("heading", { name: "Website" })).toBeVisible()
    await expect(panel(page)).toContainText("example/website")
    await expect(panel(page).getByRole("link", { name: /Ticket/ }).first()).toBeVisible()
    await expect(panel(page).getByRole("link", { name: "Edit" })).toBeVisible()
    // The context made way for the project: a link back, not a second header.
    await expect(page.locator('[data-slot="context-block"]')).toHaveCount(0)
    await expect(panel(page).getByRole("link", { name: /global context/ })).toBeVisible()

    await item(page, "Journal").click()
    await expect(panel(page).getByRole("heading", { name: "Journal" })).toBeVisible()
    await expect(panel(page)).not.toContainText("example/website")
  })

  test("the panel is the page of the project: its tabs, its figures, its tickets", async ({ page }) => {
    await open(page)
    await item(page, "Website").click()
    for (const name of ["Tickets", "Ideas", "Brief", "Settings"]) await expect(tab(panel(page), name)).toBeVisible()
    await expect(tab(panel(page), "Tickets")).toHaveAttribute("aria-selected", "true")
    await expect(panel(page).locator('[data-slot="statistics-band"]')).toBeVisible()
    // No way back to a list that is right there.
    await expect(panel(page).getByRole("link", { name: "Projects", exact: true })).toHaveCount(0)

    await tab(panel(page), "Brief").click()
    await expect(panel(page).getByText("The brief of Website.")).toBeVisible()
    // The list's address is the list's: the tab is the panel's to keep.
    await expect(page).not.toHaveURL(/tab=/)

    // And the panel holds its page without pushing the page sideways.
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, "no sideways scroll").toBeLessThanOrEqual(1440)
  })

  test("the tab picked is kept from one project to the next", async ({ page }) => {
    await open(page)
    await item(page, "Website").click()
    await tab(panel(page), "Ideas").click()
    await item(page, "Journal").click()
    await expect(panel(page).getByRole("heading", { name: "Journal" })).toBeVisible()
    await expect(tab(panel(page), "Ideas")).toHaveAttribute("aria-selected", "true")
  })

  test("the panel leads to the page of the project, on the same tab", async ({ page }) => {
    await open(page)
    await item(page, "Website").click()
    await tab(panel(page), "Brief").click()
    await panel(page).getByRole("link", { name: "Open the project's page" }).click()
    await expect(page).toHaveURL(/view=console\/projects\/read/)
    await expect(page).toHaveURL(/tab=brief/)
    await expect(page.getByRole("heading", { name: "Website" })).toBeVisible()
    await expect(tab(page, "Brief")).toHaveAttribute("aria-selected", "true")
    await expect(page.getByText("The brief of Website.")).toBeVisible()
    // Alone, the page has no link to itself.
    await expect(page.getByRole("link", { name: "Open the project's page" })).toHaveCount(0)
  })

  test("the project is read once, for the panel and for the page alone", async ({ page }) => {
    await open(page)
    const reads: string[] = []
    page.on("request", (request) => {
      if (/\/api\/projects\/0000000000000000000000000000cafe$/.test(new URL(request.url()).pathname))
        reads.push(request.url())
    })
    await item(page, "Website").click()
    await expect(panel(page)).toContainText("example/website")
    await item(page, "Journal").click()
    await expect(panel(page).getByRole("heading", { name: "Journal" })).toBeVisible()
    await item(page, "Website").click()
    await panel(page).getByRole("link", { name: "Open the project's page" }).click()
    await expect(page.getByRole("heading", { name: "Website" })).toBeVisible()
    await expect(tab(page, "Tickets")).toHaveAttribute("aria-selected", "true")
    expect(reads).toHaveLength(1)
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("a project picked opens its page", async ({ page }) => {
    await open(page)
    await expect(panel(page)).toHaveCount(0)
    await item(page, "Website").click()
    await expect(page).toHaveURL(/view=console\/projects\/read/)
    await expect(page.getByRole("heading", { name: "Website" })).toBeVisible()
    await expect(panel(page)).toHaveCount(0)
  })
})
