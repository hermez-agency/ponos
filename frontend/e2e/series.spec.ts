import { expect, test, type Page } from "@playwright/test"

/* The series: a column's tickets, one after another, in one window.
 *
 * `e2e/console.py series` serves a board of its own — three blocked tickets,
 * on a question, on an access and on a stop Ponos tries again by itself, the
 * last with the highest priority of the three, and two in review — because a
 * series goes through a whole column, and counts every card of it: no other
 * test may move one. Each test puts the cards back where they were first, so
 * that none depends on the one before it.
 */

const COLOUR = "000000000000000000000000005e0001"
const KEY = "000000000000000000000000005e0002"
const BUILD = "000000000000000000000000005e0003"
const DARK = "000000000000000000000000005e0004"
const FOOTER = "000000000000000000000000005e0005"
const START: Record<string, string> = {
  [COLOUR]: "blocked",
  [KEY]: "blocked",
  [BUILD]: "blocked",
  [DARK]: "review",
  [FOOTER]: "review",
}

/** A card moved the way another tab, or Notion, would move it: not through this page. */
async function move(page: Page, id: string, column: string) {
  const response = await page.request.post(`/api/tickets/${id}/status`, {
    data: { column },
    headers: { "X-Ponos": "1" },
  })
  expect(response.ok()).toBe(true)
}

const columns = async (page: Page) =>
  ((await (await page.request.get("/api/board")).json()) as { tickets: { id: string; column: string }[] }).tickets

/** The console, once every card of the series is back where it started: a series takes its order when it opens. */
async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  for (const ticket of await columns(page))
    if (START[ticket.id] && ticket.column !== START[ticket.id]) await move(page, ticket.id, START[ticket.id])
  await expect
    .poll(async () => (await columns(page)).filter((ticket) => START[ticket.id] === ticket.column).length, {
      timeout: 15_000,
    })
    .toBe(Object.keys(START).length)
  await page.goto(path)
}

const series = (page: Page) => page.locator("[data-series-window]")
const position = (page: Page) => series(page).locator('[data-slot="series-position"]')
const shown = (page: Page) => series(page).locator("[data-series-ticket]")
const entries = (page: Page) => series(page).locator("[data-series-entry]")
const recap = (page: Page) => series(page).locator('[data-slot="series-recap"]')

/** Every choice numbered 1, 2, 3… with its key, none drawn as chosen, and the ways out apart, last. */
async function numbered(page: Page) {
  const choices = series(page).locator('[data-slot="decision-choices"] [data-solution]')
  const drawn = await choices.evaluateAll((all) =>
    all.map((one) => [one.getAttribute("data-key"), one.getAttribute("data-variant"), one.textContent?.trim() ?? ""])
  )
  expect(drawn.length).toBeGreaterThan(1)
  drawn.forEach(([key, variant, text], index) => {
    expect(key).toBe(String(index + 1))
    expect(variant).toBe("outline")
    expect(text?.startsWith(`${index + 1}.`)).toBe(true)
  })
  for (const away of await series(page).locator('[data-slot="decision-away"] [data-solution]').all())
    expect(["abandon", "reject"]).toContain(await away.getAttribute("data-solution"))
}

/** The ticket on screen, and its panel read: its choices drawn. */
async function on(page: Page, id: string, at: string) {
  await expect(shown(page)).toHaveAttribute("data-series-ticket", id)
  await expect(position(page)).toHaveText(at)
  await expect(series(page).locator('[data-slot="decision-choices"]')).toBeVisible()
}

test.describe("on a desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("Unblock (3) goes through the blocked tickets, the question first, and ends on what was done", async ({ page }) => {
    await open(page)
    const button = page.locator('[data-series="blocked"]')
    await expect(button).toHaveText("Unblock (3)", { timeout: 15_000 })
    await button.click()
    await expect(page).toHaveURL(/[?&]series=blocked/)
    await expect(series(page).getByRole("heading", { name: "Unblock" })).toBeVisible()
    // The question, then the access, then what Ponos tries again by itself — whatever their priority.
    await expect(entries(page)).toHaveCount(3)
    expect(await entries(page).evaluateAll((all) => all.map((one) => one.getAttribute("data-series-entry")))).toEqual([
      COLOUR,
      KEY,
      BUILD,
    ])
    await on(page, COLOUR, "1 / 3")
    await expect(shown(page)).toBeFocused()
    await expect(shown(page)).toHaveAttribute("aria-label", "Ticket 1 of 3 — Pick the colour")
    await expect(shown(page).getByRole("heading", { name: "Pick the colour" })).toBeVisible()
    await expect(shown(page)).toContainText("Studio")
    await expect(shown(page).locator('[data-slot="series-cause"]')).toHaveAttribute("data-code", "session.question")
    await expect(shown(page).locator('[data-talk="question"]')).toContainText("Which way do you prefer?")
    await numbered(page)

    // The key 1 is the session's first option: answered, and on to the next.
    await page.keyboard.press("1")
    await expect(series(page).locator('[data-slot="series-settled"]')).toContainText("Ticket unblocked")
    await on(page, KEY, "2 / 3")
    await expect(entries(page).first()).toHaveAttribute("data-outcome", "done")

    await series(page).getByRole("button", { name: "Install it yourself and tell me" }).click()
    await on(page, BUILD, "3 / 3")
    await page.keyboard.press("2")
    await expect(recap(page)).toContainText("3 tickets unblocked")
    await expect(recap(page).getByRole("button", { name: "Review the skipped tickets" })).toHaveCount(0)

    const said = (await (await page.request.get(`/api/tickets/${COLOUR}/talk`)).json()) as {
      messages: { text: string }[]
    }
    expect(said.messages[said.messages.length - 1].text).toContain("Decision: option 1, “Give me an SSH key”.")
    await recap(page).getByRole("button", { name: "Close" }).click()
    await expect(series(page)).toBeHidden()
    await expect(page).not.toHaveURL(/series=/)
  })

  test("Skip and Previous, the keys, and the skipped tickets reviewed again — from the series' own address", async ({ page }) => {
    await open(page, "/?series=blocked")
    await on(page, COLOUR, "1 / 3")
    await series(page).locator('[data-slot="series-skip"]').click()
    await on(page, KEY, "2 / 3")
    await expect(entries(page).first()).toHaveAttribute("data-outcome", "skipped")
    await page.keyboard.press("ArrowLeft")
    await on(page, COLOUR, "1 / 3")
    await page.keyboard.press("j")
    await on(page, KEY, "2 / 3")
    // Straight to the last, from the list.
    await entries(page).nth(2).click()
    await on(page, BUILD, "3 / 3")
    await page.keyboard.press("k")
    await on(page, KEY, "2 / 3")
    await page.keyboard.press("ArrowRight")
    await on(page, BUILD, "3 / 3")
    await page.keyboard.press("ArrowRight")
    await expect(recap(page)).toContainText("0 tickets unblocked, 3 tickets skipped")
    await recap(page).getByRole("button", { name: "Review the skipped tickets" }).click()
    await on(page, COLOUR, "1 / 3")
    // The ticket's own page, in a tab of its own.
    await expect(series(page).getByRole("link", { name: "Open the ticket" })).toHaveAttribute("target", "_blank")
    await page.keyboard.press("Escape")
    await expect(series(page)).toBeHidden()
    await expect(page).not.toHaveURL(/series=/)
  })

  test("a ticket that moves elsewhere leaves the series as it happens", async ({ page }) => {
    await open(page, "/?series=blocked")
    await on(page, COLOUR, "1 / 3")
    // Another one, behind: the list loses it, and the count with it.
    await move(page, BUILD, "ready")
    await expect(entries(page)).toHaveCount(2, { timeout: 15_000 })
    await expect(position(page)).toHaveText("1 / 2")
    // The one on screen: said, and the next one comes.
    await move(page, COLOUR, "ready")
    await on(page, KEY, "1 / 1")
    await expect(entries(page)).toHaveCount(1)
  })

  test("Decide (2) goes through the tickets in review, and the last decision can be taken back", async ({ page }) => {
    await open(page)
    const button = page.locator('[data-series="review"]')
    await expect(button).toHaveText("Decide (2)", { timeout: 15_000 })
    await button.click()
    await expect(page).toHaveURL(/[?&]series=review/)
    await on(page, DARK, "1 / 2")
    await expect(shown(page).locator('[data-slot="decision-delivered"]')).toContainText(
      "Adds a share button under each article."
    )
    await numbered(page)
    // Reject is the last of all, apart: its key opens its note, and nothing moves before Confirm.
    const reject = series(page).locator('[data-slot="decision-away"] [data-solution="reject"]')
    const choices = series(page).locator('[data-slot="decision-choices"] [data-solution]')
    await expect(choices.last()).toHaveAttribute("data-solution", "reject")
    await page.keyboard.press((await reject.getAttribute("data-key")) ?? "")
    await expect(reject).toHaveAttribute("data-variant", "destructive")
    await series(page).getByRole("button", { name: "Confirm" }).click()
    const settled = series(page).locator('[data-slot="series-settled"]')
    await expect(settled).toContainText("Ticket decided")
    await on(page, FOOTER, "2 / 2")
    // Taken back: in review again, and on screen again.
    await settled.getByRole("button", { name: "Undo" }).click()
    await on(page, DARK, "1 / 2")
    await expect(entries(page).first()).toHaveAttribute("data-outcome", "")
    await expect
      .poll(async () => (await columns(page)).find((ticket) => ticket.id === DARK)?.column, { timeout: 15_000 })
      .toBe("review")
    await series(page).locator('[data-slot="series-skip"]').click()
    await on(page, FOOTER, "2 / 2")
    await series(page).locator('[data-slot="series-skip"]').click()
    await expect(recap(page)).toContainText("0 tickets decided, 2 tickets skipped")
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test("the series is the whole screen, and the ticket's choices read in full", async ({ page }) => {
    await open(page, "/?series=blocked")
    await on(page, COLOUR, "1 / 3")
    // Once it has grown in: it opens from slightly smaller.
    await expect.poll(async () => JSON.stringify(await series(page).boundingBox())).toBe(
      JSON.stringify({ x: 0, y: 0, width: 390, height: 844 })
    )
    for (const choice of await series(page).locator('[data-slot="decision-choices"] button').all()) {
      const drawn = await choice.boundingBox()
      expect((drawn?.x ?? 0) + (drawn?.width ?? 0)).toBeLessThanOrEqual(390)
    }
    await series(page).locator('[data-slot="series-skip"]').tap()
    await on(page, KEY, "2 / 3")
  })
})
