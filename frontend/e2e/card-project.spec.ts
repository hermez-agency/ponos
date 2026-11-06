import { expect, test, type Page } from "@playwright/test"

/* The foot of a card names its project with the project's icon, and the name
 * is a link to the project's page: a click on it goes there without opening
 * the ticket, a click on the rest of the card still opens the ticket. */

const FOOTED = "00000000000000000000000000f007ed"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
}

async function check(page: Page) {
  const card = page.locator(`[data-ticket-card="${FOOTED}"]`).filter({ visible: true }).first()
  await expect(card).toBeVisible()
  const link = card.locator('[data-slot="ticket-project"]')
  await expect(link).toContainText("Journal")
  await expect(link).toContainText("📝")
  await expect(link).toHaveAttribute("aria-label", /Journal/)
  await expect(link).toHaveAttribute("title", "Journal")

  // Clear of the bar along the bottom of a phone, which would take the click.
  // Cards further down are drawn lazily, so the page moves under the first scroll.
  await expect(async () => {
    await link.evaluate((element) => element.scrollIntoView({ block: "center", inline: "center" }))
    const box = await link.boundingBox()
    const height = page.viewportSize()!.height
    expect(box && box.y > 0 && box.x > 0 && box.x + box.width < page.viewportSize()!.width && box.y + box.height < height - 40).toBe(true)
  }).toPass()
  const at = (await link.boundingBox())!
  await page.mouse.click(at.x + at.width / 2, at.y + at.height / 2)
  await expect(page).toHaveURL(/projects\/read\//)
  await expect(page.getByRole("dialog")).toHaveCount(0)

  await page.goBack()
  await expect(card).toBeVisible()
  await card.getByRole("link", { name: "Write the journal entry" }).click()
  await expect(page.getByRole("dialog")).toBeVisible()
}

test("the project on a card has its icon and leads to its page, not to the ticket", async ({ page }) => {
  await open(page)
  await check(page)
})

test("the same on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await open(page)
  // A phone's board draws one column at a time, and opens on Blocked: the card is in Ready.
  await page.locator('[data-board-tab="ready"]').click()
  await check(page)
})
