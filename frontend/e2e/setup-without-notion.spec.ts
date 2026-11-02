import { expect, test } from "@playwright/test"

/* The first connection on the configuration `install.sh` used to leave:
 * `mode = "notion"` and no token. Nobody has to edit a file — the Notion step
 * offers a board of Markdown files next to the token, and the project and the
 * demonstration ticket are then made on it.
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

  // Two roads of the same weight, and neither is taken for the visitor.
  await expect(page.getByTestId("setup-notion")).toBeVisible()
  const roads = page.getByRole("radiogroup", { name: "Where the board lives" }).getByRole("radio")
  await expect(roads).toHaveCount(2)
  await expect(page.getByTestId("board-notion")).toHaveAttribute("aria-checked", "false")
  await expect(page.getByTestId("board-markdown")).toHaveAttribute("aria-checked", "false")
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled()

  await page.getByTestId("board-markdown").click()
  await expect(page.getByTestId("board-markdown")).toHaveAttribute("aria-checked", "true")
  await expect(page.getByTestId("board-files")).toBeVisible()
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
