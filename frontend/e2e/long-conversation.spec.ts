import { expect, test, type Page } from "@playwright/test"

/* A long conversation, and a keystroke in it.
 *
 * Five hundred messages drawn at once made every keystroke in the bar pay for
 * the style of ten thousand nodes: the console now draws the last ones only,
 * and offers the earlier ones a press away. What is measured here is what the
 * person typing waits for — the work the keystroke does at once (its handlers,
 * React's render, its layout effects), then the style and layout of the frame
 * that shows it — and each of twenty keystrokes has to fit in a frame.
 *
 * The conversation is the server's own, its hydration answered here with five
 * hundred messages: nothing is written to the board, and nothing runs.
 */

const FIELD = "Ask the workspace, or type >status"
const MESSAGES = 500
const BUDGET = 16

const paragraph =
  "The board holds three tickets in **Ready**, one of them blocked on a question. " +
  "I looked at `src/ponos/runner.py` and the tests around it; the change is small:\n\n" +
  "- read the column once;\n- keep the order;\n- say why in the commit."

function conversation() {
  const start = Date.parse("2026-11-01T09:00:00Z")
  return Array.from({ length: MESSAGES }, (_, index) => {
    const you = index % 2 === 0
    const at = new Date(start + index * 60_000).toISOString()
    return {
      id: `long-${index}`,
      role: you ? "user" : "assistant",
      parts: [{ type: "text", content: you ? `Question ${index}: what is left on the board?` : `Answer ${index}. ${paragraph}` }],
      createdAt: at,
      metadata: { ponos: { role: you ? "you" : "workspace", at, ...(you ? {} : { seconds: 12, cost: 0.0123 }) } },
    }
  })
}

async function openLong(page: Page) {
  await page.route(/\/api\/chat\/[^/]+\/agui$/, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { messages: conversation(), activeRun: null, interrupts: null } })
      : route.fallback()
  )
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await page.getByRole("button", { name: "Open the console" }).click()
  const log = page.getByRole("log", { name: "Conversation" })
  await expect(log.getByText(`Answer ${MESSAGES - 1}.`)).toBeVisible()
  return log
}

test.use({ viewport: { width: 1440, height: 900 } })

test("a keystroke in a conversation of five hundred messages fits in a frame", async ({ page }) => {
  const log = await openLong(page)
  // Only the last of them are drawn.
  const drawn = await log.locator("[data-slot=said]").count()
  expect(drawn).toBeLessThanOrEqual(100)

  const field = page.getByRole("textbox", { name: FIELD })
  await field.click()
  // Settled: the hydration's own frames are not the keystrokes'.
  await page.evaluate(() => new Promise((done) => setTimeout(done, 500)))

  await page.evaluate(() => {
    const costs: number[] = []
    ;(window as unknown as { keystrokes: number[] }).keystrokes = costs
    let started = 0
    let synchronous = 0
    // First to hear the keystroke, and last: between them, the handlers and
    // React's render and effects, which a discrete event flushes before the
    // next listener runs.
    window.addEventListener("input", () => void (started = performance.now()), { capture: true })
    window.addEventListener("input", () => {
      synchronous = performance.now() - started
      requestAnimationFrame(() => {
        // The frame's own work, without its wait for the screen: the style
        // and layout the keystroke left to do, done now rather than after.
        const frame = performance.now()
        void document.documentElement.getBoundingClientRect()
        void document.querySelector("[role=log]")?.scrollHeight
        costs.push(synchronous + performance.now() - frame)
      })
    })
  })

  const words = "what is next on it"
  for (const letter of (words + "??").slice(0, 20)) {
    await page.keyboard.type(letter)
    // One keystroke at a time: each is measured alone.
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 0))))
  }
  await expect(field).toHaveValue((words + "??").slice(0, 20))

  const costs = await page.evaluate(() => (window as unknown as { keystrokes: number[] }).keystrokes)
  expect(costs).toHaveLength(20)
  const worst = Math.max(...costs)
  test.info().annotations.push({ type: "keystrokes", description: costs.map((cost) => cost.toFixed(1)).join(" ") })
  console.log(`keystrokes (ms): ${costs.map((cost) => cost.toFixed(1)).join(" ")} — worst ${worst.toFixed(1)}`)
  expect(worst, `the slowest keystroke took ${worst.toFixed(1)} ms`).toBeLessThan(BUDGET)
})

test("Show earlier draws the messages before, and the one read stays where it was", async ({ page }) => {
  const log = await openLong(page)
  const said = log.locator("[data-slot=said]")
  const before = await said.count()
  expect(before).toBeLessThan(MESSAGES)

  const earlier = log.getByRole("button", { name: "Show earlier messages" })
  await earlier.scrollIntoViewIfNeeded()
  // The first message drawn, and where it is on the screen before the press.
  const first = said.first()
  const id = await first.textContent()
  const top = await first.evaluate((element) => element.getBoundingClientRect().top)
  await earlier.click()

  await expect.poll(() => said.count()).toBeGreaterThan(before)
  const same = log.locator("[data-slot=said]").filter({ hasText: id ?? "" }).first()
  const after = await same.evaluate((element) => element.getBoundingClientRect().top)
  expect(Math.abs(after - top)).toBeLessThan(2)

  // Pressed until there is nothing before, every message is there.
  while (await earlier.isVisible()) {
    await earlier.scrollIntoViewIfNeeded()
    await earlier.click()
  }
  await expect(said).toHaveCount(MESSAGES)
})

test("a long conversation still follows its last message", async ({ page }) => {
  const log = await openLong(page)
  // At the bottom: the last message in sight, and no way back to offer.
  await expect(log.getByText(`Answer ${MESSAGES - 1}.`)).toBeInViewport()
  await expect(page.getByRole("button", { name: "Last message" })).toHaveCount(0)
  // Scrolled to the top, the way back is offered, and takes you there.
  await log.evaluate((element) => element.scrollTo({ top: 0 }))
  await page.getByRole("button", { name: "Last message" }).click()
  await expect(log.getByText(`Answer ${MESSAGES - 1}.`)).toBeInViewport()
})
