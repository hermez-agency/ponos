import { expect, test } from "@playwright/test"

/* The first connection on the configuration `install.sh` used to leave:
 * `mode = "notion"` and no token. Nobody has to edit a file — the Notion step
 * has nothing to choose: the Notion step is optional, and the project and the
 * demonstration ticket are made on Ponos's own board.
 */

test.use({ viewport: { width: 1280, height: 900 }, locale: "en-GB", timezoneId: "UTC" })

test("without Notion, the first connection reaches a project and a demonstration ticket", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "Continue" }).click()
  await page.getByLabel("Email").fill("me@example.com")
  await page.getByLabel("Password", { exact: true }).fill("one I remember")
  await page.getByLabel("The same password again").fill("one I remember")
  await page.getByRole("button", { name: "Claim the console" }).click()
  await expect(page.getByTestId("setup-provider")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()

  // No token, and nothing to choose: Notion is offered, and passing is allowed.
  await expect(page.getByTestId("setup-notion")).toBeVisible()
  await expect(page.getByRole("radiogroup")).toHaveCount(0)
  await page.getByRole("button", { name: "Continue" }).click()

  await expect(page.getByTestId("setup-github")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-project")).toBeVisible()
  await page.getByLabel("Project name").fill("First project")
  await page.getByRole("button", { name: "Create the project" }).click()
  await expect(page.getByText("The project “First project” is created.")).toBeVisible()
  await expect(page.getByText(/no Notion token/i)).toHaveCount(0)
  await page.getByRole("button", { name: "Continue" }).click()

  await expect(page.getByTestId("setup-channels")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-demo")).toBeVisible()
  await page.getByTestId("demo-start").click()
  await expect(page.getByTestId("demo-state")).toBeVisible()
  await expect(page.getByText(/no Notion token/i)).toHaveCount(0)
})
