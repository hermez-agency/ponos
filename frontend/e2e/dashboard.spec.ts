import { expect, test, type Page } from "@playwright/test"

/* The dashboard: the statistics of a period over the board, in one page.
 *
 * The statistics were a page of their own, behind an entry of the menu; they
 * are now a band at the top of the board, on the last seven days until somebody
 * picks another period. What is checked is what somebody sees: the menu names
 * the page Dashboard and has no Statistics, the band opens on seven days above
 * the tickets, a period picked is a question asked again, and the old address
 * lands on the dashboard rather than on nothing.
 */

async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
}

/** The local day `back` days before today, as the band asks for it. */
function day(back: number): string {
  const date = new Date()
  date.setDate(date.getDate() - back)
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const band = (page: Page) => page.locator('[data-slot="statistics-band"]')

test("the menu names the dashboard, and has no statistics of its own", async ({ page }) => {
  await open(page)
  const menu = page.locator('[data-slot="sidebar"]').first()
  await expect(menu.getByText("Dashboard", { exact: true })).toBeVisible()
  await expect(menu.getByText("Statistics", { exact: true })).toHaveCount(0)
})

test("the dashboard opens on the last seven days, over the tickets", async ({ page }) => {
  const asked = page.waitForRequest((request) => request.url().includes("/api/statistics"))
  await open(page)
  const url = new URL((await asked).url())
  expect(url.searchParams.get("from")).toBe(day(6))
  expect(url.searchParams.get("to")).toBe(day(0))

  await expect(band(page).getByRole("tab", { name: "7 days" })).toHaveAttribute("aria-selected", "true")
  await expect(band(page).getByText("Open", { exact: true }).first()).toBeVisible()
  const top = (await band(page).boundingBox())!.y
  const card = (await page.getByText("A long ticket").filter({ visible: true }).first().boundingBox())!.y
  expect(top, "the statistics come before the tickets").toBeLessThan(card)
})

test("a period picked is asked for again", async ({ page }) => {
  await open(page)
  for (const [name, back] of [
    ["30 days", 29],
    ["24 h", 1],
  ] as const) {
    const asked = page.waitForRequest((request) => request.url().includes("/api/statistics"))
    await band(page).getByRole("tab", { name }).click()
    expect(new URL((await asked).url()).searchParams.get("from")).toBe(day(back))
  }
})

test("the band folds into one line, and stays folded", async ({ page }) => {
  await open(page)
  await expect(band(page).getByText("Activity", { exact: true })).toBeVisible()
  await band(page).getByRole("button", { name: /Statistics/ }).click()
  await expect(band(page).getByText("Activity", { exact: true })).toBeHidden()
  await expect(band(page).getByText(/\d+ open · \d+ closed/)).toBeVisible()
  await page.reload()
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
  await expect(band(page).getByText("Activity", { exact: true })).toBeHidden()
})

test("the blocks panel is folded behind Show more, and stays as it was left", async ({ page }) => {
  await open(page)
  const panel = band(page).getByText("Blocks, by cause and week", { exact: true })
  await expect(band(page).getByText("Activity", { exact: true })).toBeVisible()
  await expect(panel).toHaveCount(0)
  await band(page).getByRole("button", { name: "Show more", exact: true }).click()
  await expect(panel.first()).toBeVisible()
  await expect(band(page).getByRole("button", { name: "Show less", exact: true })).toBeVisible()
  await page.reload()
  await expect(band(page).getByRole("button", { name: "Show less", exact: true })).toBeVisible()
  await expect(panel.first()).toBeVisible()
  await band(page).getByRole("button", { name: "Show less", exact: true }).click()
  await expect(panel).toHaveCount(0)
  await expect(band(page).getByRole("button", { name: "Show more", exact: true })).toBeVisible()
})

test("the old address of the statistics leads to the dashboard", async ({ page }) => {
  await open(page, "/?view=console/statistics/list")
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toContain("console/tickets/list")
  await expect(band(page)).toBeVisible()
})

test("one chart says the created, the closed and the open; the other what they were", async ({ page }) => {
  // Figures of our own: what is checked is how they are drawn.
  await page.route("**/api/statistics*", async (route) => {
    const answer = await route.fetch()
    const figures = await answer.json()
    figures.totals = { ...figures.totals, created: 9, closed: 4, open: 5 }
    figures.days = [
      { day: day(2), created: 4, closed: 1, open: 3, cost: 0 },
      { day: day(1), created: 3, closed: 2, open: 4, cost: 3.42 },
      { day: day(0), created: 2, closed: 1, open: 5, cost: 3.42 },
    ]
    figures.made = {
      unit: "day",
      buckets: [day(2), day(1), day(0)],
      cells: [
        { bucket: day(2), kind: "code", subtype: "bug", project: "Opoil", count: 3 },
        { bucket: day(2), kind: "code", subtype: "feature", project: "Opoil", count: 1 },
        { bucket: day(1), kind: "code", subtype: "feature", project: "Website", count: 3 },
        { bucket: day(0), kind: "code", subtype: "", project: "Website", count: 2 },
      ],
      before: [{ kind: "code", subtype: "bug", project: "Opoil", count: 2 }],
    }
    await route.fulfill({ response: answer, json: figures })
  })
  await open(page)
  await expect(band(page).getByText("Open tickets", { exact: true })).toHaveCount(0)

  const chart = band(page).locator('[data-slot="activity-chart"]')
  const box = (await chart.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  const tip = band(page).locator('[data-slot="activity-tooltip"]')
  await expect(tip).toContainText("Created3")
  await expect(tip).toContainText("Closed2")
  await expect(tip).toContainText("Open4")
  await expect(tip).toContainText("Spent per day$3.42")

  const made = band(page).locator('[data-slot="made-chart"]')
  await expect(made.getByText("Unclassified")).toBeVisible()
  // A sub-type is its colour, faded in the bars so a chart reads as one shape
  // sooner than as a wall of ink — the same hue as the legend's dot, softened
  // by the same `color-mix` the chart itself fades it with — and no emoji.
  const legend = made.locator("figure ul")
  await expect(legend).toHaveText(/^[\p{L}\p{N}\s]+$/u)
  for (const key of ["bug", "feature", "-"]) {
    const dot = legend.locator(`li[data-subtype="${key}"] [data-slot="subtype-dot"]`)
    const bar = made.locator(`[data-slot="made-bucket"] [data-subtype="${key}"]`).first()
    const colour = await dot.evaluate((element) => getComputedStyle(element).backgroundColor)
    expect(colour).not.toBe("rgba(0, 0, 0, 0)")
    const faded = await page.evaluate((colour) => {
      const probe = document.createElement("div")
      probe.style.background = `color-mix(in oklab, ${colour} 75%, transparent)`
      document.body.append(probe)
      const resolved = getComputedStyle(probe).backgroundColor
      probe.remove()
      return resolved
    }, colour)
    await expect(bar).toHaveCSS("background-color", faded)
  }
  // 3 bugs over 3 bugs and 4 features; the period before was all bugs.
  await expect(made.locator('[data-slot="regression-rate"]')).toContainText("43 %")
  await expect(made.locator('[data-trend="down"]')).toBeVisible()

  // The per-project table is folded until asked for.
  await expect(made.locator('[data-slot="made-projects"]')).toHaveCount(0)
  const more = made.getByRole("button", { name: /^See by project \(\d+\)/ })
  await expect(more).toHaveAttribute("aria-expanded", "false")
  await more.click()
  await expect(made.getByRole("button", { name: "Hide" })).toHaveAttribute("aria-expanded", "true")
  const projects = made.locator('[data-slot="made-projects"] tbody tr')
  await expect(projects.first()).toHaveAttribute("data-project", "Opoil")
  await projects.first().click()
  await expect(made.locator('[data-slot="regression-rate"]')).toContainText("75 %")
  await expect(made.locator('[data-slot="made-projects"]')).toHaveCount(0)
})

test("the tickets created by type open on every type, so they add up to the card", async ({ page }) => {
  // One ticket created, with no type: the card counts it, so must the chart.
  await page.route("**/api/statistics*", async (route) => {
    const answer = await route.fetch()
    const figures = await answer.json()
    figures.totals = { ...figures.totals, created: 1 }
    figures.projects = [{ name: "", count: 1 }]
    figures.made = {
      unit: "day",
      buckets: [day(1), day(0)],
      cells: [{ bucket: day(0), kind: "", subtype: "", project: "", count: 1 }],
      before: [],
    }
    await route.fulfill({ response: answer, json: figures })
  })
  await open(page)

  const made = band(page).locator('[data-slot="made-chart"]')
  await expect(made.getByRole("combobox", { name: "Type" })).toHaveText("All types")
  await expect(made.locator('figure ul li[data-subtype="-"]')).toHaveText("Unclassified1")

  // A type that has none says which, rather than that nothing was created.
  await made.getByRole("combobox", { name: "Type" }).click()
  await page.getByRole("option", { name: "Code" }).click()
  await expect(made).toContainText("No Code ticket created in the period.")

  await made.getByRole("combobox", { name: "Type" }).click()
  await page.getByRole("option", { name: "No type" }).click()
  await expect(made.locator('figure ul li[data-subtype="-"]')).toHaveText("Unclassified1")
})
