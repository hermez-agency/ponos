import { expect, test, type Page } from "@playwright/test"

/* The list of schedules, read in French on a phone.
 *
 * Both rows were last read by a pass three weeks ago. The one turned off since
 * will never fire, and used to show that stale date as its next one; the one
 * still on fires on the next pass, which is not three weeks ago either. The
 * rule is said in a sentence, in the console's language. And at 390px each
 * schedule is a card, its switch, its next date and its name on the screen,
 * not past an edge a table scrolls to.
 */

const LIST = "/?view=console/schedules/list&variant=table"

test.use({ viewport: { width: 390, height: 844 }, locale: "fr-FR" })

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await expect(page.getByText("Test email")).toBeVisible()
}

const row = (page: Page, name: string) => page.locator("[data-schedule-card]", { hasText: name })

test("a paused schedule has no next date, and the rule is said in French", async ({ page }) => {
  await open(page)
  const paused = row(page, "Test email")
  await expect(paused).toContainText("Chaque heure à :00")
  await expect(paused).not.toContainText("Hourly")
  // Nothing made yet by the one on: no "Last" at all, not a dash.
  await expect(row(page, "Weekly digest")).not.toContainText("Dernière")
  await expect(paused).toContainText("en pause")
  await expect(paused).not.toContainText("09/09/2026")
  // The one still on is due: it fires on the next pass, not three weeks ago.
  await expect(row(page, "Weekly digest")).not.toContainText("09/09/2026")
  await expect(page.getByText("1 active sur 2")).toBeVisible()
})

test("at 390px each schedule is a card, its switch, next date and name on the screen", async ({ page }) => {
  await open(page)
  await expect(page.locator('[data-slot="table"]')).toHaveCount(0)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0)
  const paused = row(page, "Test email")
  for (const part of [paused.getByRole("switch"), paused.getByText("en pause"), paused.getByRole("link", { name: "Test email" })]) {
    const box = await part.boundingBox()
    expect(box, "drawn").not.toBeNull()
    expect(box!.x + box!.width).toBeLessThanOrEqual(390)
  }
  // The last date is one line, not "09/09/202" over "6 - 21:00".
  const last = paused.locator('[data-slot="badge"]')
  const box = await last.boundingBox()
  expect(box!.height).toBeLessThan(30)
})

test("the search, the project and the state live in the address", async ({ page }) => {
  await open(page)
  await page.getByPlaceholder("Chercher une récurrence").fill("digest")
  await expect.poll(() => decodeURIComponent(decodeURIComponent(page.url()))).toContain('"q":"digest"')
  await expect(row(page, "Weekly digest")).toBeVisible()
  await expect(row(page, "Test email")).toHaveCount(0)
  await page.goto(`${LIST}&filter=${encodeURIComponent(JSON.stringify({ state: "paused" }))}`)
  await expect(row(page, "Test email")).toBeVisible()
  await expect(row(page, "Weekly digest")).toHaveCount(0)
  await page.goto(`${LIST}&filter=${encodeURIComponent(JSON.stringify({ q: "nope" }))}`)
  await expect(page.getByText("Aucune récurrence ne correspond")).toBeVisible()
  // The bar has its own, the empty page says it again: either clears it.
  await page.getByRole("button", { name: "Effacer la recherche" }).last().click()
  await expect(row(page, "Weekly digest")).toBeVisible()
})

test("a schedule's name opens it in the window of the board, full screen on a phone", async ({ page }) => {
  await open(page)
  await row(page, "Test email").getByRole("link", { name: "Test email" }).click()
  const window_ = page.getByRole("dialog")
  await expect(window_.locator('[data-slot="dialog-title"]')).toHaveText("Modifier la récurrence")
  await expect(window_.locator('[data-slot="dialog-header"]')).toContainText("Test email")
  await expect(window_.getByText("Ce que Ponos doit faire à chaque fois").first()).toBeVisible()
  await expect
    .poll(async () => {
      const box = await window_.boundingBox()
      return box && [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)]
    })
    .toEqual([0, 0, 390, 844])
  await page.keyboard.press("Escape")
  await expect(window_).not.toBeAttached()
  await expect(page).toHaveURL(/schedules\/list/)
})

test("the window's button leads to the schedule's page", async ({ page }) => {
  await open(page)
  await row(page, "Test email").getByRole("link", { name: "Test email" }).click()
  await page.getByRole("dialog").getByRole("link", { name: "Ouvrir en page complète" }).click()
  await expect(page).toHaveURL(/schedules\/update\/[0-9a-f]+/)
  await expect(page.getByRole("dialog")).not.toBeAttached()
})

/* The play button, with the launch answered by the test rather than the board:
 * a real ticket would be one more card for every other spec to count. What is
 * checked here is the page's half — the button, its guard, the toast. */
async function launchAnswers(page: Page, answer: { status: number; body: unknown }) {
  const calls: string[] = []
  await page.route("**/api/schedules/*/launch", async (route) => {
    calls.push(route.request().url())
    await new Promise((resolve) => setTimeout(resolve, 400))
    await route.fulfill({ status: answer.status, json: answer.body })
  })
  return calls
}

test("a paused schedule is launched from its row, once however many times it is clicked", async ({ page }) => {
  const calls = await launchAnswers(page, { status: 200, body: { ticket: "abc", title: "Test email — 2026-10-14" } })
  await open(page)
  const button = row(page, "Test email").getByRole("button", { name: "Lancer maintenant" })
  await button.dblclick()
  await expect(button).toBeDisabled()
  await expect(page.getByText("Ticket créé")).toBeVisible()
  await expect(page.getByText("Test email — 2026-10-14")).toBeVisible()
  await expect(button).toBeEnabled()
  expect(calls).toHaveLength(1)
  // Still paused: launching a schedule does not turn it on.
  await expect(row(page, "Test email")).toContainText("en pause")
})

test("a launch that fails says why", async ({ page }) => {
  await launchAnswers(page, { status: 502, body: { error: "the board: refused" } })
  await open(page)
  await row(page, "Test email").getByRole("button", { name: "Lancer maintenant" }).click()
  await expect(page.getByText("La récurrence n'a pas pu être lancée")).toBeVisible()
  // In the page's language: the server's English is a key of `french.ts`.
  await expect(page.getByText("Le tableau : refused")).toBeVisible()
})

test("the opened schedule has the button in its header", async ({ page }) => {
  const calls = await launchAnswers(page, { status: 200, body: { ticket: "abc", title: "Test email — 2026-10-14" } })
  await open(page)
  await row(page, "Test email").getByRole("link", { name: "Test email" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Lancer maintenant" }).click()
  await expect(page.getByText("Ticket créé")).toBeVisible()
  expect(calls).toHaveLength(1)
})

test.describe("on a desktop", () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test("the table says the rule in one column, and the switch writes only itself", async ({ page }) => {
    const sent: unknown[] = []
    await page.route(/\/api\/schedules\/[0-9a-f]+$/, async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      sent.push(route.request().postDataJSON())
      await route.fulfill({ json: { id: "x" } })
    })
    await open(page)
    const header = page.locator('[data-slot="table-header"]')
    await expect(header).toContainText("Règle")
    for (const gone of ["Cadence", "À", "Jour"]) await expect(header.getByText(gone, { exact: true })).toHaveCount(0)
    const paused = page.locator('[data-slot="table-row"]', { hasText: "Test email" })
    await expect(paused).toContainText("Chaque heure à :00")
    await paused.getByRole("switch").click()
    await expect.poll(() => sent).toEqual([{ active: true }])
  })
})

test("with the calendar switched off, the page says so and leads to the switch", async ({ page }) => {
  await page.route(/\/api\/schedules$/, async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), enabled: false } })
  })
  await open(page)
  await expect(page.getByText("rien de tout cela ne tourne.")).toBeVisible()
  await page.getByRole("link", { name: "Activer dans les réglages" }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("console/settings/read/config/execution")
  await expect(page.locator('[data-field="runner-schedule"] button[role=switch]')).toBeFocused()
})
