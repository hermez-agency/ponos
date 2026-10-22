import { expect, test, type Page } from "@playwright/test"

/* A card in progress before its first step: the dot stands in front of
 * « starting… » on one line, and a long model name is cut with an ellipsis
 * inside its chip instead of at the card's edge. */

const STARTING = "000000000000000000000000000057a1"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
}

async function check(page: Page) {
  const card = page.locator(`[data-ticket-card="${STARTING}"]`)
  await expect(card).toBeVisible()
  const live = card.locator('[data-slot="card-live"]')
  const dot = live.locator("span.animate-ping").locator("..")
  const text = live.locator("p span.truncate")
  const [d, x] = await Promise.all([dot.boundingBox(), text.boundingBox()])
  expect(d && x && Math.abs(d.y + d.height / 2 - (x.y + x.height / 2)) < 6).toBe(true)

  const chip = card.locator('[data-slot="ticket-model"]')
  await expect(chip).toHaveAttribute("title", /qwen-2\.5-coder-32b-instruct/)
  const [c, box] = await Promise.all([chip.locator("..").boundingBox(), card.boundingBox()])
  expect(c && box && c.x + c.width <= box.x + box.width).toBe(true)
}

test("a card without a step puts the dot and « starting… » on one line", async ({ page }) => {
  await open(page)
  await check(page)
})

test("the same on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await open(page)
  await check(page)
})

/* « Ponos is working… », for a ticket a session has taken: on its card, and in
 * its window opened again after a reload — the window of an unblocked ticket
 * closes, and what it said while it was open is gone. */

test("a running card shows the robot at work", async ({ page }) => {
  await open(page)
  const working = page.locator(`[data-ticket-card="${STARTING}"] [data-slot="card-working"]`)
  await expect(working).toBeVisible()
  await expect(working).toContainText("Ponos is working…")
  await expect(working.locator("ponos-robot")).toHaveAttribute("state", "thinking")
})

test("its window says it too, reloaded", async ({ page }) => {
  await open(page)
  await page.goto(`/?view=console/tickets/read/${STARTING}&tab=unblock`)
  const talking = page.locator('[data-talk="working"]')
  await expect(talking).toContainText("Ponos is working…")
  await page.reload()
  await expect(talking).toContainText("Ponos is working…")
})
