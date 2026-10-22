import { expect, test, type Locator, type Page } from "@playwright/test"

/* The console on a phone: every page within reach, nothing under the bubble.
 *
 * At 390px the bottom bar held six entries in a row 540px wide that scrolled
 * sideways without saying so — Statistics cut in two, Settings past the edge —
 * and the discussion's bubble sat over the last card's link, a token's
 * "forget", the top of a chart. So the narrowest phone worth drawing for is
 * where it is checked: the bar fits, each page is a tap or two away, and at the
 * end of every page no button, link or field has the bubble over it.
 */

const PHONE = { width: 360, height: 780 }

const PAGES: [string, RegExp][] = [
  ["Dashboard", /\/\?view=console\/tickets\//],
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
    expect(labels, `the bar's labels at ${width}px`).toEqual(["Dashboard", "Projects", "Ideas", "Sessions", "More"])
    for (const label of await bar(page).getByRole("button").locator("span").all()) {
      const [scroll, client] = await label.evaluate((element) => [element.scrollWidth, element.clientWidth])
      expect(scroll, `${await label.textContent()} is cut at ${width}px`).toBeLessThanOrEqual(client)
    }
  }
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

test("at the end of every page, nothing is under the bubble", async ({ page }) => {
  await open(page)
  for (const [name, address] of PAGES) {
    await go(page, name)
    await expect(page).toHaveURL(address)
    await page.waitForLoadState("networkidle")
    // Measured again until the page has settled: a list that arrives after
    // the scroll to the end grows the page under it, and the first reading
    // then sees its last card where the bubble is — on a slow runner, a
    // failure that said nothing about the console.
    await expect(async () => {
      await page.keyboard.press("End")
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
      const covered = await page.evaluate(() => {
        const bubble = document.querySelector<HTMLElement>('button[aria-label^="Open "][aria-keyshortcuts]')
        if (!bubble) return ["no bubble"]
        const over = bubble.getBoundingClientRect()
        const nav = document.querySelector('[data-slot="admin-mobile-nav"]')
        return Array.from(document.querySelectorAll<HTMLElement>("a, button, input, textarea, select, [role=tab]"))
          .filter((element) => element !== bubble && !nav?.contains(element) && element.checkVisibility())
          .filter((element) => {
            const box = element.getBoundingClientRect()
            return box.width > 0 && box.left < over.right && box.right > over.left && box.top < over.bottom && box.bottom > over.top
          })
          .map((element) => element.getAttribute("aria-label") || element.textContent?.trim() || element.tagName)
      })
      expect(covered, `under the bubble on ${name}`).toEqual([])
      // And whatever the page ends on — a card's link, a sentence — ends above
      // it, so that a page holding a button there tomorrow is covered too.
      const [end, bubbleTop] = await page.evaluate(() => {
        const content = document.querySelector<HTMLElement>('[data-slot="admin-content"]')!
        const end = content.getBoundingClientRect().bottom - parseFloat(getComputedStyle(content).paddingBottom)
        return [end, document.querySelector('button[aria-label^="Open "][aria-keyshortcuts]')!.getBoundingClientRect().top]
      })
      expect(end, `the end of ${name} runs under the bubble`).toBeLessThanOrEqual(bubbleTop)
    }).toPass()
  }
})

test("the version, the last read and the two buttons are behind More", async ({ page }) => {
  await open(page)
  // The bar's end says whether the stream is live, at every width.
  await expect(page.locator("header").getByText(/^(live|connecting…|reconnecting…)$/)).toBeVisible()
  await bar(page).getByRole("button", { name: "More", exact: true }).click()
  const drawer = page.getByRole("dialog")
  await expect(drawer.getByText(/^v\d+\.\d+\.\d+/)).toBeVisible()
  await expect(drawer.getByText(/^synced /)).toBeVisible()
  await expect(drawer.getByRole("button", { name: "Resynchronise now" })).toBeVisible()
  await expect(drawer.getByRole("button", { name: /^(Light|Dark)$/ })).toBeVisible()
})
