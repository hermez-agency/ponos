import { expect, test } from "@playwright/test"

/* A ticket opened on its mission, then its result: the post ready to copy, the
 * session's account apart in the Journal tab — see `ticket-result.tsx`. */

const WRITTEN = "0000000000000000000000000000b0a7"
// Its twin, whose result the second test retouches: the tests run side by side.
const RETOUCHED = "0000000000000000000000000000b0a8"

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
})

test("a writing ticket opens on its mission, then its post, ready to copy", async ({ page }) => {
  await page.goto(`/?view=console/tickets/read/${WRITTEN}`)
  const tabs = page.getByRole("tablist")
  await expect(tabs.getByRole("tab")).toHaveText(["Result", "Discussion", "Live", "Journal"])
  await expect(tabs.getByRole("tab", { name: "Result" })).toHaveAttribute("aria-selected", "true")

  // The mission, folded once read: its first line, a click away from the rest.
  const mission = page.getByRole("button", { name: "Mission" })
  await expect(mission).toHaveAttribute("aria-expanded", "false")
  await expect(page.locator('[data-slot="ticket-mission"]')).toContainText("A post about shipping small")

  const body = page.locator('[data-slot="ticket-result-body"]')
  await expect(body).toContainText("Three things shipping small taught me.")
  await expect(body.locator("strong")).toHaveText("Small")
  await page.screenshot({ path: "/tmp/ponos-result.png", fullPage: true })
  // The session's account is not mixed into the post.
  await expect(page.getByRole("tabpanel")).not.toContainText("I read it twice")

  await page.getByRole("button", { name: "Copy", exact: true }).click()
  await page.getByRole("menuitem", { name: "Copy the text" }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "Three things shipping small taught me.\n\n1. Small pull requests get read.\n2. Often beats big.\n3. Alone is fine."
  )

  // What the session said of itself is the journal's.
  await page.getByRole("tab", { name: "Journal" }).click()
  await expect(page.getByRole("tabpanel")).toContainText("I read it twice before handing it back.")
  await expect(page).toHaveURL(/[?&]tab=journal$/)
  // The facts — what it cost, which model — come under what it delivered.
  await expect(page.locator('[data-slot="ticket-summary"]')).toBeVisible()
})

test("a result retouched by hand is a new version, the one before kept", async ({ page }) => {
  await page.goto(`/?view=console/tickets/read/${RETOUCHED}`)
  await page.getByRole("button", { name: "Edit" }).click()
  const editor = page.locator('[data-slot="ticket-result-editor"]')
  await editor.fill("Two things shipping small taught me.")
  await page.getByRole("button", { name: "Save" }).click()
  const body = page.locator('[data-slot="ticket-result-body"]')
  await expect(body).toHaveText("Two things shipping small taught me.")

  await page.getByRole("button", { name: "Version 2" }).click()
  await page.getByRole("menuitem", { name: /Version 1/ }).click()
  await expect(body).toContainText("Three things shipping small taught me.")
  await expect(page.locator('[data-slot="ticket-result-older"]')).toContainText("by a session")
  await page.getByRole("button", { name: "Make it the result again" }).click()
  await expect(body).toContainText("Three things shipping small taught me.")
  await expect(page.getByRole("button", { name: "Version 3" })).toBeVisible()
})

test("on a phone, the mission and the result come first, the facts under them", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/?view=console/tickets/read/${WRITTEN}`)
  const result = page.locator('[data-slot="ticket-result-body"]')
  await expect(result).toBeInViewport()
  const summary = page.locator('[data-slot="ticket-summary"]')
  const below = await summary.boundingBox()
  const above = await result.boundingBox()
  expect(below!.y).toBeGreaterThan(above!.y)
  await page.screenshot({ path: "/tmp/ponos-result-phone.png" })
})
