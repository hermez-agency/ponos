import { expect, test, type Page } from "@playwright/test"

/* Several cards at once: picked by their box, then by a click, and acted on
 * from the bar along the bottom.
 *
 * Launching them asks once, for the lot, and says how many sessions start and
 * that they are paid for. Nothing is launched here — the board is shared with
 * the other tests, which count its drafts: the window is answered Cancel.
 */

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
}

const card = (page: Page, title: string) =>
  page.locator("[data-ticket-card]").filter({ has: page.getByRole("link", { name: title, exact: true }) })

test.use({ viewport: { width: 1440, height: 900 } })

test("drafts picked by their box and a click are launched from one window, once confirmed", async ({ page }) => {
  await open(page)
  const first = card(page, "Ticket 1")
  await first.hover()
  await first.getByRole("checkbox", { name: "Select “Ticket 1”" }).click()
  const bar = page.getByRole("toolbar", { name: "Selected tickets" })
  await expect(bar).toContainText("1 ticket selected")

  // Picking, a click on a card picks it rather than opening it.
  const address = page.url()
  await card(page, "Ticket 2").getByRole("link", { name: "Ticket 2", exact: true }).click()
  await expect(bar).toContainText("2 tickets selected")
  expect(page.url()).toBe(address)
  await expect(card(page, "Ticket 2")).toHaveAttribute("data-selected", "true")

  await bar.getByRole("button", { name: "Make ready" }).click()
  const dialog = page.getByRole("alertdialog")
  await expect(dialog).toContainText("Launch 2 tickets?")
  await expect(dialog).toContainText("sessions that are paid for")
  await expect(dialog).toContainText("Ticket 1")
  await expect(dialog).toContainText("Ticket 2")
  await dialog.getByRole("button", { name: "Cancel" }).click()
  await expect(dialog).toBeHidden()
  await expect(bar).toContainText("2 tickets selected")

  // Escape lets the selection go.
  await page.keyboard.press("Escape")
  await expect(bar).toBeHidden()
  await expect(card(page, "Ticket 2")).not.toHaveAttribute("data-selected", "true")
})

for (const [name, viewport] of [
  ["desktop", { width: 1440, height: 900 }],
  ["mobile", { width: 390, height: 800 }],
] as const) {
  test(`the launch window keeps long titles and its buttons inside its frame (${name})`, async ({ page }) => {
    await open(page)
    const long = (n: number) => page.locator("[data-ticket-card]").filter({ hasText: `Draft ${n} ` }).first()
    await long(11).scrollIntoViewIfNeeded()
    await long(11).hover()
    await long(11).getByRole("checkbox").click()
    await long(12).scrollIntoViewIfNeeded()
    await long(12).hover()
    await long(12).getByRole("checkbox").click()
    // Picked on the wide board, asked on the narrow one: the window is what is measured.
    await page.setViewportSize(viewport)
    await page.getByRole("toolbar", { name: "Selected tickets" }).getByRole("button", { name: "Make ready" }).click()

    const dialog = page.getByRole("alertdialog")
    await expect(dialog).toContainText("Launch 2 tickets?")
    const frame = (await dialog.boundingBox())!
    const inside = async (locator: ReturnType<Page["locator"]>) => {
      const box = (await locator.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(frame.x - 1)
      expect(box.x + box.width).toBeLessThanOrEqual(frame.x + frame.width + 1)
    }
    await inside(dialog.locator("ul"))
    for (const item of await dialog.locator("li").all()) await inside(item)
    await inside(dialog.getByRole("button", { name: "Cancel" }))
    await inside(dialog.getByRole("button", { name: /^Launch 2 tickets/ }))
    await dialog.getByRole("button", { name: "Cancel" }).click()
    await page.keyboard.press("Escape")
  })
}
