import { expect, test, type Page } from "@playwright/test"

/* The settings' Export & import tab: an export downloaded with the boxes the
 * page ticks by default — the conversations left out — and the same file
 * dropped back, which reads its preview and writes nothing. */

const TRANSFER = "/?view=console/settings/read/config/transfer"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(TRANSFER)
}

test.use({ viewport: { width: 1440, height: 900 } })

test("an export downloads an archive, and the same archive previews without importing", async ({ page }) => {
  await open(page)
  await expect(page.getByTestId("export-tickets").getByRole("checkbox")).toBeChecked()
  await expect(page.getByTestId("export-conversations").getByRole("checkbox")).not.toBeChecked()
  await expect(page.getByTestId("export-never")).toContainText("the vault and every secret")

  const asked = page.waitForRequest("**/api/export")
  const downloading = page.waitForEvent("download")
  await page.getByTestId("export-run").click()
  const categories = (await asked).postDataJSON().categories as string[]
  expect(categories).toContain("tickets")
  expect(categories).not.toContain("conversations")
  const download = await downloading
  expect(download.suggestedFilename()).toMatch(/^ponos-export-.*\.zip$/)
  const archive = await download.path()

  let applied = false
  page.on("request", (request) => {
    if (request.url().includes("/api/import") && request.url().includes("apply=true")) applied = true
  })
  await page.getByTestId("import-file").setInputFiles(archive)
  await expect(page.getByTestId("import-preview")).toBeVisible()
  await expect(page.getByTestId("import-tickets")).toContainText("already here")
  await expect(page.getByTestId("import-conversations")).toHaveCount(0)
  expect(applied).toBe(false)
})
