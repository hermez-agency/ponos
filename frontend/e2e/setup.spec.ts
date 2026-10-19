import { expect, test } from "@playwright/test"

/* The first connection, on a console nobody has claimed.
 *
 * One walk, in order, because claiming is a gesture that happens once: the
 * account closes the door behind it, every step after it is reachable, and the
 * summary says what the console runs on — a board of files here, a `claude`
 * that is signed in as nobody. From this machine the installation code is not
 * asked; from outside it is, which `tests/run.py` holds the server to.
 */

test.use({ viewport: { width: 1280, height: 900 }, locale: "en-GB", timezoneId: "UTC" })

test("the first connection goes from the account to the summary", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "First connection" })).toBeVisible()
  // The language first: the one step nobody has to be signed in for.
  await expect(page.getByTestId("setup-language")).toBeVisible()
  await expect(page.getByTestId("language-en")).toHaveAttribute("aria-checked", "true")
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-access")).toBeVisible()
  await expect(page.getByLabel("Installation code")).toHaveCount(0)

  await page.getByLabel("Email").fill("me@example.com")
  await page.getByLabel("Password", { exact: true }).fill("short")
  await page.getByLabel("The same password again").fill("short")
  await page.getByRole("button", { name: "Claim the console" }).click()
  await expect(page.getByText("A password of 8 characters at the least.")).toBeVisible()

  await page.getByLabel("Password", { exact: true }).fill("one I remember")
  await page.getByLabel("The same password again").fill("one I remember")
  await page.getByRole("button", { name: "Claim the console" }).click()

  // Claimed: the account is no longer a step, and the provider comes next.
  await expect(page.getByTestId("setup-provider")).toBeVisible()
  await expect(page.getByRole("button", { name: /Access/ })).toHaveCount(0)
  await expect(page).toHaveURL(/step=provider/)
  const cards = page.getByRole("radiogroup", { name: "Claude provider" }).getByRole("radio")
  await expect(cards).toHaveCount(3)
  await page.getByTestId("provider-cli").click()
  await expect(page.getByTestId("provider-cli")).toHaveAttribute("aria-checked", "true")
  await expect(page.getByText("claude auth login").first()).toBeVisible()
  await page.getByRole("button", { name: "Use the CLI" }).click()
  // The e2e `claude` is signed in as nobody: written all the same, and said.
  await expect(page.getByRole("status")).toContainText("claude auth login")
  await page.getByTestId("provider-openrouter").click()
  await expect(page.getByRole("checkbox")).toBeChecked()

  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-notion")).toBeVisible()
  await expect(page.getByText("This console keeps its board in Markdown files")).toBeVisible()

  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-github")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-project")).toBeVisible()
  await expect(page.getByTestId("setup-projects-known")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByTestId("setup-channels")).toBeVisible()
  await expect(page.getByLabel("Bot token", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()
  // The first ticket is offered, not played: this `claude` is signed in as nobody.
  await expect(page.getByTestId("setup-demo")).toBeVisible()
  await expect(page.getByTestId("demo-start")).toBeVisible()
  await page.getByRole("button", { name: "Continue" }).click()

  const summary = page.getByTestId("summary-rows")
  await expect(summary).toBeVisible({ timeout: 30_000 })
  for (const row of ["machine", "provider", "model", "board", "github", "projects", "channels", "environment"])
    await expect(summary.locator(`[data-row="${row}"]`)).toHaveCount(1)
  const provider = summary.locator('[data-row="provider"]')
  await expect(provider).toHaveAttribute("data-state", "missing")
  await expect(provider).toContainText("Claude Code CLI (subscription)")
  await expect(summary.locator('[data-row="board"]')).toHaveAttribute("data-state", "ok")
  await expect(summary.locator('[data-row="board"]')).toContainText("Markdown board in")
  await expect(summary.locator('[data-row="environment"]')).toContainText("Machine — Ponos")

  // Each line leads to the step that changes it.
  await provider.getByRole("button", { name: "Claude provider" }).click()
  await expect(page.getByTestId("setup-provider")).toBeVisible()
  await expect(page.getByTestId("provider-cli")).toHaveAttribute("aria-checked", "true")

  // And the console opens, signed in by the account the first step made.
  await page.goto("/setup?step=summary")
  await page.getByRole("link", { name: "Open the console" }).click()
  await expect(page).toHaveURL(/view=console\/tickets\/list/)
  await expect(page.getByRole("heading", { name: "First connection" })).toHaveCount(0)
})
