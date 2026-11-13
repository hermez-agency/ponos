import { expect, test } from "@playwright/test"

/* A ticket finished opens on its result, the mission in a tab beside it: the
 * post ready to copy, the session's account apart in the Journal tab — see
 * `ticket-result.tsx`. Before the work is over there is no Result tab. */

const WRITTEN = "0000000000000000000000000000b0a7"
// Its twin, whose result the second test retouches: the tests run side by side.
const RETOUCHED = "0000000000000000000000000000b0a8"
// Ready, never run: a mission and nothing else.
const LONG = "000000000000000000000000000abcde"
// A code ticket in review, its pull request open and no result written.
const CODE = "00000000000000000000000000c1c103"

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
})

test("a writing ticket opens on its post, ready to copy, its mission in a tab of its own", async ({ page }) => {
  await page.goto(`/?view=console/tickets/read/${WRITTEN}`)
  const tabs = page.getByRole("tablist")
  await expect(tabs.getByRole("tab")).toHaveText(["Result", "Mission", "Discussion", "Live", "Journal"])
  await expect(tabs.getByRole("tab", { name: "Result" })).toHaveAttribute("aria-selected", "true")
  // The mission is not under the result any more: it has its tab.
  await expect(page.locator('[data-slot="ticket-mission"]')).toHaveCount(0)

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

  // The mission, whole, under one title.
  await tabs.getByRole("tab", { name: "Mission" }).click()
  await expect(page).toHaveURL(/[?&]tab=mission$/)
  const mission = page.locator('[data-slot="ticket-mission"]')
  await expect(mission).toContainText("A post about shipping small, for LinkedIn.")
  await expect(mission.getByRole("button")).toHaveCount(0)
  await expect(page.locator('[data-slot="ticket-result"]')).toHaveCount(0)

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
  await page.getByRole("button", { name: "Save", exact: true }).click()
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

test("a ticket not finished has no Result tab, and an address naming it opens the mission", async ({ page }) => {
  await page.goto(`/?view=console/tickets/read/${LONG}&tab=result`)
  const tabs = page.getByRole("tablist")
  await expect(tabs.getByRole("tab")).toHaveText(["Mission", "Discussion", "Live", "Journal"])
  await expect(tabs.getByRole("tab", { name: "Mission" })).toHaveAttribute("aria-selected", "true")
  await expect(page.getByRole("tabpanel")).toContainText("Part 40")
  await expect(page).toHaveURL(/[?&]tab=mission$/)
})

test("a code ticket that wrote no result shows its pull request in its place", async ({ page }) => {
  await page.goto(`/?view=console/tickets/read/${CODE}`)
  const tabs = page.getByRole("tablist")
  await expect(tabs.getByRole("tab", { name: "Result" })).toHaveAttribute("aria-selected", "true")
  const card = page.getByRole("tabpanel").locator('[data-slot="ticket-result-pr"]')
  await expect(card).toBeVisible()
  await expect(card.getByRole("link", { name: /^PR #/ })).toHaveAttribute("href", /\/pull\/\d+$/)
  await expect(card.getByRole("link", { name: /View the diff/ })).toHaveAttribute("href", /\/files$/)
  await expect(page.getByRole("tabpanel")).not.toContainText("No result rendered")
})

test("the Result tab comes when the ticket goes into review, without a reload", async ({ page }) => {
  const created = await page.request.post("/api/tickets", {
    headers: { "X-Ponos": "1" },
    data: { title: `Finished under the reader ${Date.now()}`, body: "Say it in two tabs.", project: "", ready: false },
  })
  expect(created.ok()).toBeTruthy()
  const { id } = (await created.json()) as { id: string }
  await page.goto(`/?view=console/tickets/read/${id}`)
  const tabs = page.getByRole("tablist")
  await expect(tabs.getByRole("tab")).toHaveText(["Mission", "Discussion", "Live", "Journal"])

  const moved = await page.request.post(`/api/tickets/${id}/status`, {
    data: { column: "review" },
    headers: { "X-Ponos": "1" },
  })
  expect(moved.ok()).toBeTruthy()
  await expect(tabs.getByRole("tab", { name: "Result" })).toBeVisible({ timeout: 15_000 })
  await expect(tabs.getByRole("tab").first()).toHaveText("Result")
  // The reader stays on the tab they were reading.
  await expect(tabs.getByRole("tab", { name: "Mission" })).toHaveAttribute("aria-selected", "true")
})

test("on a phone, the result comes first, the facts under it", async ({ page }) => {
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
