import { expect, test } from "@playwright/test"

/* The first connection on an installation nothing was written into yet:
 * nobody has to edit a file, and the project and the demonstration ticket are
 * made on Ponos's own board.
 */

test.use({ viewport: { width: 1280, height: 900 }, locale: "en-GB", timezoneId: "UTC" })

test("on a fresh installation, the first connection reaches a project and a demonstration ticket", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "Continue" }).click()
  await page.getByLabel("Email").fill("me@example.com")
  await page.getByLabel("Password", { exact: true }).fill("one I remember")
  await page.getByLabel("The same password again").fill("one I remember")
  await page.getByRole("button", { name: "Claim the console" }).click()
  await expect(page.getByTestId("setup-provider")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()

  await expect(page.getByTestId("setup-github")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-project")).toBeVisible()
  await page.getByLabel("Project name").fill("First project")
  await page.getByRole("button", { name: "Create the project" }).click()
  await expect(page.getByText("The project “First project” is created.")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()

  await expect(page.getByTestId("setup-channels")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-demo")).toBeVisible()
  await page.getByTestId("demo-start").click()
  await expect(page.getByTestId("demo-state")).toBeVisible()
})
