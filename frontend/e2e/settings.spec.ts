import { expect, test, type Page } from "@playwright/test"

/* The settings are one file, and the way back to them is that file.
 *
 * The package links every record to its resource's list — "← Settings" over
 * the title, "Settings" in the bar's breadcrumb — and the settings have none:
 * both led to a page that said "Something went wrong" and nothing else. What is
 * tested is the way back from a section, an address typed by hand, and the top
 * of the page saying what it is once.
 */

const SECTION = "/?view=console/settings/read/config/communication"

async function open(page: Page, path: string) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const settingsPage = async (page: Page) => {
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toMatch(/^console\/settings\/read\/config/)
  await expect(page.getByRole("heading", { name: "Configure the runner" })).toBeVisible()
  await expect(page.getByText("Something went wrong")).toHaveCount(0)
}

test.use({ viewport: { width: 1440, height: 900 } })

test("the breadcrumb leads from a section back to the settings", async ({ page }) => {
  await open(page, SECTION)
  await settingsPage(page)
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Settings" }).click()
  await settingsPage(page)
})

for (const typed of ["/?view=console/settings", "/?view=console/settings/list"]) {
  test(`${typed} opens the settings`, async ({ page }) => {
    await open(page, typed)
    await settingsPage(page)
  })
}

test("the page has one title, and no way back to a list", async ({ page }) => {
  await open(page, SECTION)
  await settingsPage(page)
  // The layout's header is where "← Settings", the second title and "#config" were.
  await expect(page.locator('[data-slot="admin-header"]')).toHaveCount(0)
  await expect(page.getByText("#config")).toHaveCount(0)
  // Named after the page open rather than after the file.
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Communication")
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).not.toContainText("config.toml")
  await expect(page.getByRole("heading", { level: 2 })).toHaveCount(1)
  await page.getByRole("tab", { name: "General" }).click()
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("General")
})

test("the console's language is one setting in two places, each saying whose it is", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/general")
  await settingsPage(page)
  const card = page.locator('[data-card="languages"]')
  await expect(card.getByText("Language of the console, in this browser")).toBeVisible()
  await expect(card.getByText("Language of the console, by default for all")).toBeVisible()
  await expect(card.getByText("the language picked in a browser comes first", { exact: false })).toBeVisible()
})

test("the settings say what the console runs on, line by line", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/general")
  await settingsPage(page)
  await page.getByRole("button", { name: "What this console runs on" }).click()
  const summary = page.getByTestId("summary-rows")
  await expect(summary.locator("[data-row]")).toHaveCount(7, { timeout: 30_000 })
  await expect(summary.locator('[data-row="board"]')).toHaveAttribute("data-state", "ok")
  await summary.locator('[data-row="channels"]').getByRole("link", { name: "Change" }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("console/settings/read/config/communication")
})

test("eight pages (six from the file, then GitHub and MCP), and an old link to a section opens the page it is on", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/notify")
  await settingsPage(page)
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("console/settings/read/config/communication")
  await expect(page.getByRole("tab")).toHaveCount(8)
  await expect(page.locator('[data-card="notify"]')).toBeVisible()
})

test("a search opens the right page and unfolds what hid the field", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/general")
  await settingsPage(page)
  await expect(page.locator('[data-fold="mapping"]')).toHaveCount(0)
  await page.getByRole("searchbox", { name: "Search the settings" }).fill("notion.status.ready")
  await page.getByRole("option").first().click()
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("console/settings/read/config/source")
  await expect(page.locator('[data-field="notion-status-ready"]')).toBeVisible()
})

test("the keys are hidden until asked for", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/execution")
  await settingsPage(page)
  const key = page.locator("code").getByText("runner.max_concurrent", { exact: true })
  await expect(key).toHaveCount(0)
  await page.getByText("Show keys").click()
  await expect(key).toBeVisible()
  await page.getByText("Show keys").click()
  await expect(key).toHaveCount(0)
})

test("the models are one table, and a change waits under a bar that sticks", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/models")
  await settingsPage(page)
  const grid = page.getByTestId("model-grid")
  // Four levels by four types, and three shifts by eight sub-types under them.
  await expect(grid.getByRole("radio")).toHaveCount(16 + 24)
  const subtypes = page.getByTestId("model-grid-subtypes")
  await expect(subtypes.getByRole("radio", { name: "Security — One level higher" })).toBeChecked()
  await expect(subtypes.getByRole("radio", { name: "Docs — One level lower" })).toBeChecked()
  await expect(subtypes.getByRole("radio", { name: "Bug — Same as Code" })).toBeChecked()
  const bar = page.getByTestId("settings-bar")
  await expect(bar.getByRole("status")).toHaveText("No changes")
  await grid.getByRole("radio", { name: "Code — Heavy work" }).check()
  await expect(bar.getByRole("status")).toHaveText("Unsaved changes")
  await expect(bar).toHaveCSS("position", "sticky")
  await bar.getByRole("button", { name: "Cancel" }).click()
  await expect(bar.getByRole("status")).toHaveText("No changes")
})
