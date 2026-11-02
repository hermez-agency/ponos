import { expect, test, type Locator, type Page } from "@playwright/test"

import { underTheCorner } from "./corner"

/* The console on a phone: every page within reach, nothing under the bubble.
 *
 * At 390px the bottom bar held six entries in a row 540px wide that scrolled
 * sideways without saying so — Statistics cut in two, Settings past the edge —
 * and the discussion's bubble sat over the last card's link, a token's
 * "forget", the top of a chart. So the narrowest phone worth drawing for is
 * where it is checked: the bar fits, each page is a tap or two away, and no
 * button, link or field has the bubble over it — on a phone there is none, the
 * discussion opens from More.
 */

const PHONE = { width: 360, height: 780 }
/** A ticket with a journal, so its Live tab has a button to cover. */
const ASKING = "00000000000000000000000000000a5c"

const PAGES: [string, RegExp][] = [
  ["Board", /\/\?view=console\/tickets\//],
  ["Projects", /\/\?view=console\/projects\//],
  ["Schedules", /\/\?view=console\/schedules\//],
  ["Ideas", /\/\?view=console\/ideas\//],
  ["Settings", /\/\?view=console\/settings\//],
]

test.use({ viewport: PHONE })

async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  await expect(page.getByRole("button", { name: "More", exact: true })).toBeVisible()
}

/** The package's bottom bar. */
const bar = (page: Page): Locator => page.locator('[data-slot="admin-mobile-nav"]')

/** Go to a page the way a thumb would: the bar, or the bar's More. */
async function go(page: Page, name: string) {
  const direct = bar(page).getByRole("button", { name, exact: true })
  if (await direct.count()) {
    await direct.click()
    return
  }
  await bar(page).getByRole("button", { name: "More", exact: true }).click()
  const drawer = page.getByRole("dialog")
  await drawer.getByRole("button", { name, exact: true }).click()
  await expect(drawer).toBeHidden()
}

test("the bottom bar fits the screen and scrolls nowhere", async ({ page }) => {
  await open(page)
  const row = bar(page).locator("> div").first()
  const [scroll, client] = await row.evaluate((element) => [element.scrollWidth, element.clientWidth])
  expect(scroll, "the bar's entries run past its edge").toBeLessThanOrEqual(client)
  for (const button of await bar(page).getByRole("button").all()) {
    const box = (await button.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width)
  }
})

test("each label of the bottom bar is read whole, at 360 and at 390", async ({ page }) => {
  for (const width of [360, 390]) {
    await page.setViewportSize({ width, height: PHONE.height })
    await open(page)
    const labels = await bar(page).getByRole("button").locator("span").allTextContents()
    expect(labels, `the bar's labels at ${width}px`).toEqual(["Board", "Projects", "Ideas", "Sessions", "More"])
    for (const label of await bar(page).getByRole("button").locator("span").all()) {
      const [scroll, client] = await label.evaluate((element) => [element.scrollWidth, element.clientWidth])
      expect(scroll, `${await label.textContent()} is cut at ${width}px`).toBeLessThanOrEqual(client)
    }
  }
})

/* At 375px, in either language, nothing the bar over the page or the bar along
 * the bottom names is cut: "Tableau de bord" ran past both, and a ticket's
 * title has no length at all. Every page the audit found one cut on. */
test("at 375px no label of the two bars is cut, in English or in French", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  for (const [language, first] of [["en", "Board"], ["fr", "Tableau"]]) {
    await page.addInitScript((code) => localStorage.setItem("ponos-language", code), language)
    for (const path of [
      "/",
      "/?view=console/schedules/list",
      "/?view=console/tickets/read/00000000000000000000000000000a5c",
      "/?view=console/settings/read/config/communication",
    ]) {
      await page.goto(path)
      // Read once the language's words are in: French is fetched after the page.
      await expect(bar(page).getByRole("button").first()).toHaveText(first)
      const labels = [
        ...(await bar(page).getByRole("button").locator("span").all()),
        ...(await page.locator("header").first().locator("a span, nav, nav li, nav li > *").all()),
      ]
      for (const label of labels) {
        if (!(await label.isVisible())) continue
        const [scroll, client] = await label.evaluate((element) => [element.scrollWidth, element.clientWidth])
        expect(scroll, `« ${await label.textContent()} » is cut on ${path} in ${language}`).toBeLessThanOrEqual(client)
      }
    }
  }
})

/* At 375 × 812 the first idea started at 520px and the first schedule at
 * 440px, under a head that said in four lines what the bar had just named: the
 * sentence under the title, a row of gestures, five statuses on two lines and
 * the filters on a third. The head is a title, a line of controls and a line of
 * filters now, the rest behind "⋯" and "Filters" — and the first row of either
 * list is on the screen without a scroll. The ideas are the route's: this board
 * has none, and writing some would count on the others' tests. */
const IDEA = {
  id: 1, scope: "global", project: "", kind: "ticket", category: "ux", score: 80, score_reason: "",
  score_error: "", scoring: false, title: "Read the header at a glance", description: "On a phone.", where: "",
  done: [], out: [], status: "proposed", ticket: "", created: "", decided_at: null,
  created_at: "2026-11-01T10:00:00+00:00", changed_at: "2026-11-01T10:00:00+00:00", origin: "ponos",
  author: { kind: "ponos", name: "", avatar: "" }, edited: null,
}

test("at 375 × 812 the first idea and the first schedule are in sight without a scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.route("**/api/ideas/all*", (route) =>
    route.fulfill({
      json: { scope: "all", project: "", ideas: [IDEA], counts: { proposed: 1, kept: 0, discarded: 0, ticket: 0 } },
    })
  )
  for (const [path, first] of [
    ["/?view=console/ideas/list", '[data-slot="ideas-item"]'],
    ["/?view=console/schedules/list", "[data-schedule-item]"],
  ]) {
    await open(page, path)
    const row = page.locator(first).first()
    await expect(row).toBeVisible()
    await expect(page.locator('[data-slot="list-header"] h2 + p')).toBeHidden()
    expect(await page.evaluate(() => window.scrollY), `${path} opens scrolled`).toBe(0)
    expect((await row.boundingBox())!.y, `the first row of ${path} is under the fold`).toBeLessThan(300)
  }
  // What the head no longer shows is a tap away: the swipe and the settings behind "⋯".
  await open(page, "/?view=console/ideas/list")
  const find = page.getByRole("button", { name: "Ponos, find me ideas", exact: true })
  await expect(find).toBeHidden()
  await page.getByRole("button", { name: "More actions" }).click()
  await expect(find).toBeVisible()
  await expect(page.locator('[data-slot="ideas-settings"]')).toBeVisible()
})

test("every page is a tap or two away", async ({ page }) => {
  await open(page)
  for (const [name, address] of PAGES) {
    await go(page, name)
    await expect(page).toHaveURL(address)
  }
})

test("the menu down the left has no More beside a phone", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible()
  await expect(page.getByRole("button", { name: "More", exact: true })).toHaveCount(0)
})

/* At 375px, nothing of the page under the discussion's button: there is none
 * on a phone. Every screen of the page is checked where the bubble stood — the
 * corner over the bottom bar — by asking the browser what a tap at each
 * clickable thing there would land on. The Ideas page is checked in its own
 * spec, where there are ideas. */
test("at 375px, a tap in the corner over the bar lands on what the page draws there", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await open(page)
  for (const path of ["/", `/?view=console/tickets/read/${ASKING}&tab=live`]) {
    await page.goto(path)
    await page.waitForLoadState("networkidle")
    await expect(page.getByRole("button", { name: "Open the console" })).toBeHidden()
    expect(await underTheCorner(page), `covered on ${path}`).toEqual([])
  }
  // Something was there to be covered: the live tab's own button, at its turn.
  await expect(page.getByRole("button", { name: "Unfold everything" })).toBeVisible()
})

test("a phone opens the discussion from More, the drawer of More closed behind it", async ({ page }) => {
  await open(page)
  await bar(page).getByRole("button", { name: "More", exact: true }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Open the console" }).click()
  const talk = page.getByRole("dialog", { name: "the console" })
  await expect(talk).toBeVisible()
  await expect(page.getByRole("dialog")).toHaveCount(1)
  await expect(talk.getByRole("textbox")).toBeFocused()
})

test("the version, the last read and the two buttons are behind More", async ({ page }) => {
  await open(page)
  // The bar's end says whether the stream is live, at every width.
  await expect(page.locator("header").getByText(/^(live|connecting…|reconnecting…)$/)).toBeVisible()
  await bar(page).getByRole("button", { name: "More", exact: true }).click()
  const drawer = page.getByRole("dialog")
  await expect(drawer.getByText(/^v\d+\.\d+\.\d+/)).toBeVisible()
  await expect(drawer.getByText(/^synced /)).toBeVisible()
  await expect(drawer.getByRole("button", { name: /^Switch to the (light|dark) theme$/ })).toBeVisible()
  // A reread says it is on its way, then that it is done.
  let reads = 0
  await page.route("**/api/refresh", async (route) => {
    reads += 1
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({ json: { ok: true } })
  })
  const reread = drawer.getByRole("button", { name: "Resynchronise now" })
  await reread.click()
  await expect(reread).toBeDisabled()
  await expect(page.getByText("Board read again")).toBeVisible()
  await expect(reread).toBeEnabled()
  expect(reads).toBe(1)
})
