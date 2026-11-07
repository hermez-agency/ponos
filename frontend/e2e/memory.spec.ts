import { expect, test, type Page } from "@playwright/test"

/* The Context page's Memory tab: what Ponos remembers from one session to the next.
 *
 * What is tested is the way a person goes: proposals wait at the top and are
 * read by nobody until accepted, a refused one stays out, a memory is added,
 * filtered, searched, edited and deleted, and a memory that came from a ticket
 * leads back to it. The console is seeded with one kept fact and two proposals
 * (`e2e/console.py`, `memory_of`).
 */

const MEMORY = "/?view=console/context/read/context/memory"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(MEMORY)
  await expect(page.locator('[data-slot="memory-page"]')).toBeVisible()
}

const rows = (page: Page) => page.locator('[data-slot="memory-row"]')

// One memory for the whole console: the tests that write it do not run side by side.
test.describe.configure({ mode: "serial" })
test.use({ viewport: { width: 1440, height: 900 } })

test("the tab sits beside the others, and the proposals wait at the top", async ({ page }) => {
  await open(page)
  await expect(page.getByRole("tab", { name: "Memory", exact: true })).toBeVisible()
  const waiting = page.locator('[data-slot="memory-proposals"]')
  await expect(waiting.getByText("No session reads these until you accept them.")).toBeVisible()
  await expect(waiting.locator('[data-slot="memory-row"]')).toHaveCount(2)
  await expect(page.getByText("Prefers short reports.")).toBeVisible()

  // Only the kept one is read by a session: the API says it too.
  const kept = await (await page.request.get("/api/memories?status=accepted")).json()
  expect(kept.memories.map((memory: { text: string }) => memory.text)).toEqual(["Prefers short reports."])
})

test("a memory that came from a ticket leads back to it", async ({ page }) => {
  await open(page)
  const row = rows(page).filter({ hasText: "The client signs off on Fridays." })
  await row.locator('[data-slot="memory-origin"]').click()
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toMatch(/^console\/tickets\/read\//)
})

test("a proposal is accepted, another refused, and a refused one stays out", async ({ page }) => {
  await open(page)
  const waiting = page.locator('[data-slot="memory-proposals"]')
  await waiting.locator('[data-slot="memory-row"]').filter({ hasText: "signs off on Fridays" }).getByRole("button", { name: "Accept" }).click()
  await waiting.locator('[data-slot="memory-row"]').filter({ hasText: "early riser" }).getByRole("button", { name: "Refuse" }).click()
  await expect(waiting).toHaveCount(0)

  const kept = await (await page.request.get("/api/memories?status=accepted")).json()
  expect(kept.memories.map((memory: { text: string }) => memory.text).sort()).toEqual([
    "Prefers short reports.",
    "The client signs off on Fridays.",
  ])
  await page.getByLabel("Filter by state").selectOption("refused")
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText("early riser")
})

test("a memory is added, filtered, searched, edited and deleted", async ({ page }) => {
  await open(page)
  await page.getByRole("button", { name: "Add a memory" }).click()
  const editor = page.locator('[data-slot="memory-editor"]')
  await editor.getByLabel("The fact").fill("It is a ROG Ally X, not a Steam Deck.")
  await editor.getByLabel("Type").selectOption("reference")
  await editor.getByRole("button", { name: "Save", exact: true }).click()
  await expect(page.getByText("It is a ROG Ally X, not a Steam Deck.")).toBeVisible()

  await page.getByLabel("Filter by type").selectOption("reference")
  await expect(rows(page)).toHaveCount(1)
  await page.getByLabel("Filter by type").selectOption("")

  await page.getByLabel("Search the memory").fill("ROG")
  await expect(rows(page)).toHaveCount(1)

  await rows(page).first().getByRole("button", { name: "Edit" }).click()
  await editor.getByLabel("The fact").fill("It is a ROG Ally X.")
  await editor.getByRole("button", { name: "Save", exact: true }).click()
  await expect(page.getByText("It is a ROG Ally X.", { exact: true })).toBeVisible()

  await rows(page).first().getByRole("button", { name: "Delete" }).click()
  await expect(page.getByText("Memory deleted")).toBeVisible()
  await expect(rows(page)).toHaveCount(0)
})
