import { expect, test, type Page } from "@playwright/test"

/* A card in progress before its first step says « Ponos is working… ·
 * starting… » on one line, cut inside the card rather than at its edge; its
 * model, however long, is the title's tooltip, no longer a chip. */

const STARTING = "000000000000000000000000000057a1"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
}

async function check(page: Page) {
  const card = page.locator(`[data-ticket-card="${STARTING}"]`)
  await expect(card).toBeVisible()
  const working = card.locator('[data-slot="card-working"]')
  const doing = working.locator('[data-slot="card-doing"]')
  await expect(doing).toContainText("starting…")
  const [w, x, box] = await Promise.all([working.boundingBox(), doing.boundingBox(), card.boundingBox()])
  // One line: what it does sits beside the robot, not under it, and inside the card.
  expect(w && x && Math.abs(w.y + w.height / 2 - (x.y + x.height / 2)) < 6).toBe(true)
  expect(x && box && x.x + x.width <= box.x + box.width).toBe(true)

  await expect(card.locator('[data-slot="card-title"] a')).toHaveAttribute("title", /qwen-2\.5-coder-32b-instruct/)
  await expect(card.locator('[data-slot="ticket-model"]')).toHaveCount(0)
}

test("a card without a step says « starting… » on the robot's line", async ({ page }) => {
  await open(page)
  await check(page)
})

test("the same on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await open(page)
  // A phone's board draws one column at a time, and opens on Blocked: the card is in progress.
  await page.locator('[data-board-tab="running"]').click()
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

/* A card in progress between two sessions says which phase it is in, and for
 * how long — not « starting… » for as long as its CI runs. */

test("a card waiting for its CI says so, and since when", async ({ page }) => {
  await open(page)
  const live = page.locator('[data-ticket-card="0000000000000000000000000000c1a1"] [data-slot="card-live"]')
  await expect(live.locator('[data-slot="card-phase"]')).toHaveText(/waiting for the CI of PR #417 · for /)
  await expect(live).not.toContainText("starting…")
})
