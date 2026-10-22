import { expect, test, type Locator, type Page } from "@playwright/test"

/* A card is carried to another column by hand, wherever it is picked up.
 *
 * Picked up by its title — a link, which the browser would rather carry as an
 * address — or by the line along its bottom, a Blocked card dropped on Ready is
 * drawn in Ready, and the board says it is Ready once the write has landed.
 * The drop is made on a card of the Ready column: that column is drawn
 * whatever the other tests do, and a card is part of its column.
 */

const LONG = "000000000000000000000000000abcde"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await expect(page.locator(`[data-ticket-card="${LONG}"]`)).toBeVisible()
}

/** Whether two cards are drawn in the same column. */
const together = (card: Locator, other: string) =>
  card.evaluate(
    (element, id) =>
      element.closest("div:has(> header)") ===
      document.querySelector(`[data-ticket-card="${id}"]`)?.closest("div:has(> header)"),
    other
  )

test.use({ viewport: { width: 1440, height: 900 } })

for (const [id, title, grip] of [
  ["0000000000000000000000000000d7a1", "A card dragged by its title", "title"],
  ["0000000000000000000000000000d7a2", "A card dragged by its foot", "foot"],
] as const) {
  test(`a card picked up by its ${grip} moves to the column it is dropped in`, async ({ page }) => {
    await open(page)
    const card = page.locator(`[data-ticket-card="${id}"]`)
    await expect(card).toBeVisible()
    expect(await together(card, LONG)).toBe(false)

    const handle = grip === "title" ? card.getByRole("link", { name: title }) : card.locator(".border-t")
    await handle.dragTo(page.locator(`[data-ticket-card="${LONG}"]`))

    await expect.poll(() => together(card, LONG)).toBe(true)
    await expect
      .poll(async () => {
        const tickets = (await (await page.request.get("/api/board")).json()).tickets as {
          id: string
          status: string
          sync?: string
        }[]
        const ticket = tickets.find((item) => item.id === id)
        return `${ticket?.status} ${ticket?.sync ?? ""}`.trim()
      })
      .toBe("Ready")
    // Still there once the page is read again: what moved is the ticket.
    await page.reload()
    await expect(page.locator(`[data-ticket-card="${LONG}"]`)).toBeVisible()
    await expect.poll(() => together(card, LONG)).toBe(true)
  })
}
