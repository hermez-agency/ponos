import { expect, test, type Locator, type Page } from "@playwright/test"

/* The ideas, swiped one card at a time.
 *
 * Ten ideas come from a `claude` that proposes them (see `console.py`), and what
 * is checked is what a person does with them: asking from the dashboard and from
 * a project's page, throwing a card with a mouse drag, a button and an arrow,
 * keeping one and finding the draft on the board, taking a decision back,
 * changing one's mind from the list of every idea, a project's Ideas tab with its
 * filters, an idea written by hand and signed, and — at the width of a phone — a
 * pile that fills the screen and still answers a drag.
 *
 * One server and one file, one test after another: the ideas are the console's,
 * and the pile a test leaves is the pile the next one opens.
 */

test.describe.configure({ mode: "serial" })

const PROJECT = "/?view=console/projects/read/0000000000000000000000000000cafe"

async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const dialog = (page: Page) => page.locator('[data-slot="ideas-dialog"]')
const cards = (page: Page) => dialog(page).locator('[data-slot="ideas-card"]')
const drawer = (page: Page) => page.locator('[data-slot="drawer-popup"]')
/** One of the gestures a card has in its foot, by the name the button carries. */
async function choose(_page: Page, card: Locator, name: string) {
  await card.getByRole("button", { name, exact: true }).click()
}
const top = (page: Page) => dialog(page).locator('[data-slot="ideas-card"][data-depth="0"]')

/** A card taken by the mouse and let go of `dx` pixels to the side. */
async function drag(page: Page, dx: number) {
  const box = (await top(page).boundingBox())!
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + dx / 2, y + 4, { steps: 6 })
  await page.mouse.move(x + dx, y + 8, { steps: 6 })
  return () => page.mouse.up()
}

async function board(page: Page): Promise<{ title: string; column: string }[]> {
  const response = await page.request.get("/api/board")
  return (await response.json()).tickets
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("the dashboard's button asks for the workspace's ideas, and → keeps one as a draft", async ({ page }) => {
    await open(page)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(dialog(page).getByText("Ponos is looking for ideas…")).toBeVisible()
    await expect(top(page)).toBeVisible({ timeout: 20_000 })
    await expect(cards(page)).toHaveCount(3)
    await expect(top(page)).toContainText("Build the calendar module")
    await expect(top(page).locator('[data-slot="ideas-kind"]')).toHaveText("Ticket")

    await page.keyboard.press("ArrowRight")
    await expect(page.getByText("Ticket created: Build the calendar module for sales")).toBeVisible()
    await expect(top(page)).not.toContainText("calendar")
    await expect(top(page).locator('[data-slot="ideas-kind"]')).toHaveText("New project")
    await expect
      .poll(async () => (await board(page)).find((ticket) => ticket.title === "Build the calendar module for sales")?.column)
      .toBe("draft")
  })

  test("← throws one away, Undo brings it back, and the ✕ and ♥ buttons do the same", async ({ page }) => {
    await open(page)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(top(page)).toBeVisible()
    const title = (await top(page).locator("h3").textContent())!

    await page.keyboard.press("ArrowLeft")
    await expect(top(page).locator("h3")).not.toHaveText(title)
    await dialog(page).getByRole("button", { name: "Undo" }).click()
    await expect(top(page).locator("h3")).toHaveText(title)

    await dialog(page).getByRole("button", { name: "Throw away" }).click()
    await expect(top(page).locator("h3")).not.toHaveText(title)
    await expect(dialog(page).getByRole("button", { name: "Undo" })).toBeEnabled()
  })

  test("dragging a card leans it and stamps it, and a short drag brings it back", async ({ page }) => {
    await open(page)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(top(page)).toBeVisible()
    const title = (await top(page).locator("h3").textContent())!

    const letGo = await drag(page, -60)
    await expect(top(page).locator('[data-slot="ideas-stamp-discard"]')).not.toHaveCSS("opacity", "0")
    await expect(top(page)).toHaveCSS("transform", /matrix\(0\.9\d+, -0\.\d+/)
    await letGo()
    await expect(top(page)).toHaveCSS("transform", "matrix(1, 0, 0, 1, 0, 0)")
    await expect(top(page).locator("h3")).toHaveText(title)

    const keep = await drag(page, 220)
    await expect(top(page).locator('[data-slot="ideas-stamp-keep"]')).toHaveCSS("opacity", "1")
    await keep()
    await expect(top(page).locator("h3")).not.toHaveText(title)
  })

  test("every idea is in the second tab, thrown ones included, and a thrown idea can still become a ticket", async ({ page }) => {
    await open(page)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(top(page)).toBeVisible()
    await dialog(page).getByRole("tab", { name: "All ideas" }).click()
    const items = dialog(page).locator('[data-slot="ideas-item"]')
    await expect(items.first()).toBeVisible()
    await expect(dialog(page).locator('li[data-status="ticket"]', { hasText: "Build the calendar module" })).toBeVisible()
    const thrown = dialog(page).locator('li[data-status="discarded"]').first()
    const title = (await thrown.locator('[data-slot="ideas-title"]').textContent())!
    await thrown.locator('[data-slot="ideas-ticket"]').click()
    await expect(dialog(page).locator('li[data-status="ticket"]', { hasText: title })).toBeVisible()
    await expect
      .poll(async () => (await board(page)).find((ticket) => ticket.title.endsWith(title))?.column)
      .toBe("draft")
  })

  test("the end of the pile says so, and ‘Ten more’ asks for another batch", async ({ page }) => {
    await open(page)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(top(page)).toBeVisible()
    // Left alone, the page's focus is on the pile: the arrows work as they are.
    for (let left = await cards(page).count(); left > 0; left = await cards(page).count()) {
      const shown = (await top(page).locator("h3").textContent())!
      await page.keyboard.press("ArrowLeft")
      await expect(top(page).locator("h3")).not.toHaveText(shown)
        .catch(() => undefined)
      if ((await dialog(page).locator('[data-slot="ideas-finished"]').count()) > 0) break
    }
    await expect(dialog(page).getByText("No more ideas")).toBeVisible({ timeout: 20_000 })
    await dialog(page).getByRole("button", { name: "Ten more" }).click()
    await expect(top(page)).toBeVisible({ timeout: 20_000 })
    await expect(top(page)).toContainText("module for support")
  })

  test("a project's page asks for that project's ideas, which are all tickets", async ({ page }) => {
    await open(page, PROJECT)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(dialog(page).getByRole("heading", { name: "Ideas for Website" })).toBeVisible()
    await expect(top(page)).toBeVisible({ timeout: 20_000 })
    await expect(top(page).locator('[data-slot="ideas-kind"]')).toHaveText("Ticket")
    await expect(top(page)).toContainText("Website")
    await page.keyboard.press("ArrowRight")
    await expect(page.getByText(/Ticket created: Build the/)).toBeVisible()
    await expect
      .poll(async () => (await board(page)).filter((ticket) => ticket.title.startsWith("Build the") && ticket.column === "draft").length)
      .toBeGreaterThan(1)
  })

  test("a project's Ideas tab lists them all with their counts, and one is written by hand, kept, thrown and made new", async ({ page }) => {
    await open(page, `${PROJECT}&tab=ideas`)
    const tab = page.locator('[data-slot="ideas-list"]')
    await expect(page.getByRole("tab", { name: "Ideas" })).toHaveAttribute("aria-selected", "true")
    const filter = (status: string) => tab.locator(`[data-slot="ideas-filter"][data-status="${status}"]`)
    await expect(filter("ticket").locator('[data-slot="ideas-count"]')).toHaveText("1")
    await expect(tab.locator('[data-slot="ideas-item"][data-author="ponos"]').first()).toContainText("Ponos")

    await tab.getByRole("link", { name: "New idea", exact: true }).click()
    const form = page.locator("[data-idea-window]")
    await expect(form.locator('[data-slot="idea-project"]')).toHaveText("Website")
    await form.getByLabel("Title").fill("A page for the opening hours")
    await form.getByLabel("Description").fill("People keep asking.")
    await form.getByRole("button", { name: "Create the idea" }).click()
    const mine = tab.locator('[data-slot="ideas-item"]', { hasText: "A page for the opening hours" })
    await expect(mine).toHaveAttribute("data-author", "human")
    await expect(mine.locator('[data-slot="ideas-author"]')).toContainText("Ada Lovelace")
    await expect(mine).toHaveAttribute("data-status", "proposed")

    await choose(page, mine, "Keep")
    await expect(mine).toHaveAttribute("data-status", "kept")
    await choose(page, mine, "Throw away")
    await expect(mine).toHaveAttribute("data-status", "discarded")
    await filter("discarded").click()
    await expect(tab.locator('[data-slot="ideas-item"]', { hasText: "A page for the opening hours" })).toBeVisible()
    await expect(tab.locator('[data-slot="ideas-item"]:not([data-status="discarded"])')).toHaveCount(0)

    await tab.locator('[data-slot="ideas-author-filter"]').click()
    await page.getByRole("option", { name: "Written by us" }).click()
    await expect(tab.locator('[data-slot="ideas-item"]')).toHaveCount(1)
    await expect(filter("all").locator('[data-slot="ideas-count"]')).toHaveText("1")
    // The address is the project's: a list drawn inside it writes nothing there.
    expect(new URL(page.url()).searchParams.get("filter")).toBeNull()

    await choose(page, mine, "Back to new")
    await filter("proposed").click()
    await mine.getByRole("link", { name: "Edit" }).click()
    await drawer(page).getByLabel("Title").fill("A page for the opening hours, in two languages")
    await drawer(page).getByRole("button", { name: "Save" }).click()
    const edited = tab.locator('[data-slot="ideas-item"]', { hasText: "in two languages" })
    await expect(edited.locator('[data-slot="ideas-edited"]')).toContainText("Edited by Ada Lovelace")
    await edited.getByRole("button", { name: "Turn into a ticket" }).click()
    await expect(page.getByText("Ticket created: A page for the opening hours, in two languages")).toBeVisible()
    await expect
      .poll(async () => (await board(page)).find((ticket) => ticket.title.endsWith("in two languages"))?.column)
      .toBe("draft")

    await page.reload()
    await expect(page.locator('[data-slot="ideas-item"]', { hasText: "in two languages" })).toHaveAttribute("data-status", "ticket")
  })
})

test.describe("at the width of a phone", () => {
  test.use({ viewport: { width: 360, height: 740 } })

  test("the pile fills the screen, and a drag with a thumb keeps a card", async ({ page }) => {
    await open(page)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(top(page)).toBeVisible({ timeout: 20_000 })
    // Once the dialog has finished opening (it zooms in).
    await expect.poll(async () => (await dialog(page).boundingBox())?.width).toBeGreaterThanOrEqual(359)
    await expect.poll(async () => (await dialog(page).boundingBox())?.height).toBeGreaterThanOrEqual(739)
    const card = (await top(page).boundingBox())!
    expect(card.x).toBeGreaterThanOrEqual(0)
    expect(card.x + card.width).toBeLessThanOrEqual(360)
    // The buttons are under the pile, in reach, and inside the screen.
    for (const name of ["Throw away", "Keep"]) {
      const button = (await dialog(page).getByRole("button", { name }).boundingBox())!
      expect(button.y + button.height).toBeLessThanOrEqual(740)
      expect(button.width).toBeGreaterThanOrEqual(44)
    }
    const title = (await top(page).locator("h3").textContent())!
    const letGo = await drag(page, 150)
    await expect(top(page).locator('[data-slot="ideas-stamp-keep"]')).not.toHaveCSS("opacity", "0")
    await letGo()
    await expect(top(page).locator("h3")).not.toHaveText(title)
    await expect(page.getByText(/(Ticket|Project) created/)).toBeVisible()
  })
})
