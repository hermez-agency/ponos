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
