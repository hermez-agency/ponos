import { expect, test, type Locator, type Page } from "@playwright/test"

/* The Ideas page: every idea in one place, with the project it is for.
 *
 * The ideas come from the same fake `claude` as the swipe's spec (see
 * `console.py`). What is checked is what somebody does with the page: reaching
 * it from the menu, finding the ideas Ponos asked for in it, the project's name
 * on its ideas, the filters and the address that keeps them, the category an
 * idea is sorted into, its score and the order by relevance, the gestures
 * of a card — the one in sight and the ones in its menu —, reading one and
 * writing one, and turning an idea into a ticket of the right project — and, at
 * the width of a phone, a single column inside the screen.
 *
 * One server and one file, one test after another: the ideas are the console's.
 */

test.describe.configure({ mode: "serial" })

const PROJECT = "/?view=console/projects/read/0000000000000000000000000000cafe"
const PAGE = "/?view=console/ideas/list"

async function open(page: Page, path = PAGE) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const cards = (page: Page) => page.locator('[data-slot="ideas-item"]')
const origin = (page: Page, name: string) => page.locator('[data-slot="idea-origin"]', { hasText: name })
const status = (page: Page, key: string) => page.locator(`[data-slot="ideas-filter"][data-status="${key}"]`)
const drawer = (page: Page) => page.locator('[data-slot="drawer-popup"]')
const ideaWindow = (page: Page) => page.locator("[data-idea-window]")
/** What the address says the list is filtered on. */
const filterOf = (page: Page) => {
  // Written by the package encoded once more than a search parameter is.
  let said = new URL(page.url()).searchParams.get("filter") || "{}"
  while (!said.startsWith("{")) said = decodeURIComponent(said)
  return JSON.parse(said)
}

/** One of the gestures a card has in its foot, by the name the button carries. */
async function choose(_page: Page, card: Locator, name: string) {
  await card.getByRole("button", { name, exact: true }).click()
}

/** Ask for a batch from the page's button, sort nothing, and close the swipe. */
async function ask(page: Page) {
  await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
  await expect(page.locator('[data-slot="ideas-card"]').first()).toBeVisible({ timeout: 20_000 })
  await page.keyboard.press("Escape")
  await expect(cards(page).first()).toBeVisible()
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("the menu has an Ideas entry that opens the page, and what is asked for appears in it", async ({ page }) => {
    await open(page, "/")
    await page.getByRole("link", { name: "Ideas", exact: true }).click()
    await expect(page).toHaveURL(/view=console\/ideas\/list/)
    await expect(page.getByRole("heading", { name: "Ideas", exact: true })).toBeVisible()
    await ask(page)
    await expect(cards(page).first().locator('[data-slot="ideas-status"]')).toHaveText("New")
    await expect(page.locator('[data-slot="ideas-kind"]', { hasText: "Ticket" }).first()).toBeVisible()
    await expect(origin(page, "Workspace").first()).toBeVisible()
  })

  test("New idea is at the top of the list", async ({ page }) => {
    await open(page)
    const header = page.locator('[data-slot="list-header"]')
    await expect(header.getByRole("link", { name: "New idea", exact: true })).toBeVisible()
  })

  test("a project's ideas carry its name, and the filters narrow the list", async ({ page }) => {
    await open(page, PROJECT)
    await page.getByRole("button", { name: "Ponos, find me ideas", exact: true }).click()
    await expect(page.locator('[data-slot="ideas-card"]').first()).toBeVisible({ timeout: 20_000 })
    await page.keyboard.press("Escape")

    await open(page)
    await expect(cards(page).first()).toBeVisible()
    const all = await cards(page).count()
    const website = cards(page).filter({ has: origin(page, "Website") })
    await expect(website.first()).toBeVisible()
    const mine = await website.count()
    expect(mine).toBeLessThan(all)

    const filter = page.locator('[data-slot="ideas-project-filter"]')
    await filter.click()
    await page.getByRole("option", { name: "Website" }).click()
    await expect(cards(page)).toHaveCount(mine)
    await filter.click()
    await page.getByRole("option", { name: "Workspace" }).click()
    await expect(cards(page).first()).toBeVisible()
    await expect(origin(page, "Website")).toHaveCount(0)

    await filter.click()
    await page.getByRole("option", { name: "All projects" }).click()
    await status(page, "kept").click()
    await expect(cards(page)).toHaveCount(0)
    await expect(page.getByText("No idea matches these filters.")).toBeVisible()
  })

  test("keep, throw away and back to new move an idea between states", async ({ page }) => {
    await open(page)
    await status(page, "proposed").click()
    const title = (await cards(page).first().locator('[data-slot="ideas-title"]').textContent())!
    const mine = () => cards(page).filter({ hasText: title })

    // Every gesture in sight, none in a menu.
    await expect(mine().getByRole("button", { name: "Turn into a ticket" })).toBeVisible()
    await expect(mine().getByRole("button", { name: "Keep", exact: true })).toBeVisible()
    await expect(mine().getByRole("button", { name: "Throw away", exact: true })).toBeVisible()
    await expect(mine().getByRole("button", { name: "Back to new", exact: true })).toHaveCount(0)
    await expect(mine().locator('[data-slot="ideas-menu"]')).toHaveCount(0)

    await choose(page, mine(), "Keep")
    await status(page, "kept").click()
    await expect(mine()).toHaveAttribute("data-status", "kept")
    await choose(page, mine(), "Back to new")
    await expect(mine()).toHaveCount(0)

    await status(page, "proposed").click()
    await choose(page, mine(), "Throw away")
    await status(page, "discarded").click()
    await expect(mine()).toHaveAttribute("data-status", "discarded")
    await choose(page, mine(), "Back to new")
    await expect(mine()).toHaveCount(0)
  })

  test("an idea of a project becomes a draft ticket of that project", async ({ page }) => {
    await open(page)
    const filter = page.locator('[data-slot="ideas-project-filter"]')
    await filter.click()
    await page.getByRole("option", { name: "Website" }).click()
    await status(page, "proposed").click()
    const title = (await cards(page).first().locator('[data-slot="ideas-title"]').textContent())!
    // By its title: the list may still be settling into its order.
    await cards(page).filter({ hasText: title }).getByRole("button", { name: "Turn into a ticket" }).click()
    await expect(page.getByText(`Ticket created: ${title}`)).toBeVisible()
    await status(page, "ticket").click()
    await expect(cards(page).filter({ hasText: title }).getByRole("link", { name: "Open the ticket" })).toBeVisible()
    const board = (await (await page.request.get("/api/board")).json()).tickets as {
      title: string
      column: string
      project: string
    }[]
    const made = board.find((ticket) => ticket.title === title)
    expect(made?.column).toBe("draft")
    expect(made?.project).toBeTruthy()
  })
  test("the filters are in the address, and a reload or a shared link opens the same list", async ({ page }) => {
    await open(page)
    await expect(cards(page).first()).toBeVisible()
    await status(page, "proposed").click()
    const filter = page.locator('[data-slot="ideas-project-filter"]')
    await filter.click()
    await page.getByRole("option", { name: "Website" }).click()
    await page.locator('[data-slot="ideas-author-filter"]').click()
    await page.getByRole("option", { name: "Written by Ponos" }).click()
    await expect.poll(() => filterOf(page)).toMatchObject({ status: "proposed", author: "ponos" })
    expect(filterOf(page).project).toBeTruthy()
    const shown = await cards(page).count()
    expect(shown).toBeGreaterThan(0)
    const address = page.url()

    await page.reload()
    await expect(cards(page)).toHaveCount(shown)
    await expect(status(page, "proposed")).toHaveAttribute("aria-pressed", "true")
    await expect(filter).toContainText("Website")
    await expect(page.locator('[data-slot="ideas-author-filter"]')).toContainText("Written by Ponos")
    for (const card of await cards(page).all()) {
      await expect(card).toHaveAttribute("data-status", "proposed")
      await expect(card).toHaveAttribute("data-author", "ponos")
    }

    await open(page, address)
    await expect(cards(page)).toHaveCount(shown)
    // Back to "all": nothing left in the address.
    await page.getByRole("button", { name: "Clear the search" }).first().click()
    await expect(status(page, "all")).toHaveAttribute("aria-pressed", "true")
    await expect.poll(() => Object.keys(filterOf(page)).length).toBe(0)
  })

  test("a list the filters empty says so, and its button brings the ideas back", async ({ page }) => {
    await open(page)
    await page.locator('[data-slot="ideas-author-filter"]').click()
    await page.getByRole("option", { name: "Written by us" }).click()
    await status(page, "ticket").click()
    await expect(page.getByText("No idea matches these filters.")).toBeVisible()
    await page.getByRole("button", { name: "Clear the filters" }).click()
    await expect(cards(page).first()).toBeVisible()
  })

  test("an idea says its category, the filter keeps one category, and the form sorts one", async ({ page }) => {
    await open(page)
    await expect(cards(page).first()).toBeVisible()
    await expect(page.locator('[data-slot="ideas-category"][data-category="security"]').first()).toHaveText("Security")
    await page.locator('[data-slot="ideas-category-filter"]').click()
    await page.getByRole("option", { name: "Security" }).click()
    await expect.poll(() => filterOf(page)).toMatchObject({ category: "security" })
    await expect(cards(page).filter({ hasNot: page.locator('[data-category="security"]') })).toHaveCount(0)
    // One that can still be reworded: an idea turned into a ticket cannot.
    const editable = cards(page).filter({ has: page.locator('[data-slot="ideas-edit"]') }).first()
    const title = (await editable.locator('[data-slot="ideas-title"]').textContent())!
    const sorted = cards(page).filter({ hasText: title })
    await sorted.locator('[data-slot="ideas-edit"]').click()
    // The package's select: a combobox of its own, opened, then an option picked.
    await drawer(page).getByRole("group").filter({ hasText: "Category" }).getByRole("combobox").click()
    await page.getByRole("option", { name: "Tech", exact: true }).click()
    await drawer(page).getByRole("button", { name: "Save" }).click()
    await expect(cards(page).filter({ hasText: title })).toHaveCount(0)
    await page.getByRole("button", { name: "Clear the search" }).first().click()
    await expect(
      cards(page).filter({ hasText: title }).locator('[data-slot="ideas-category"]')
    ).toHaveAttribute("data-category", "technical")
  })

  test("a card shows its score in its colour, and the most relevant come first", async ({ page }) => {
    await open(page)
    await expect(cards(page).first()).toBeVisible()
    const pill = (tone: string) => page.locator(`[data-slot="ideas-score"][data-tone="${tone}"]`).first()
    await expect(pill("green")).toHaveText(/^\d+$/)
    expect(Number(await pill("green").textContent())).toBeGreaterThanOrEqual(70)
    await expect(pill("red")).toHaveText(/^\d+$/)
    expect(Number(await pill("red").textContent())).toBeLessThan(40)
    await expect(pill("unscored")).toHaveText("Not scored")
    const colour = (tone: string) => pill(tone).evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(await colour("green")).not.toBe(await colour("red"))
    await pill("green").hover()
    await expect(page.locator('[data-slot="ideas-score-reason"]').first()).toContainText(
      "Worth it for the people who asked."
    )

    await page.locator('[data-slot="ideas-order"]').click()
    await page.getByRole("option", { name: "Most relevant first" }).click()
    await expect.poll(() => filterOf(page)).toMatchObject({ sorted: "relevance" })
    await expect(cards(page).first().locator('[data-slot="ideas-score"]')).toHaveAttribute("data-tone", "green")
    const said = await cards(page).locator('[data-slot="ideas-score"]').allTextContents()
    const scores = said.map((text) => (/^\d+$/.test(text) ? Number(text) : -1))
    expect(scores).toEqual([...scores].sort((a, b) => b - a))

    // The new ideas rest on relevance, with nothing in the address to say so.
    await page.getByRole("button", { name: "Clear the search" }).first().click()
    await status(page, "proposed").click()
    await expect(page.locator('[data-slot="ideas-order"]')).toContainText("Most relevant first")
    await expect(cards(page).first().locator('[data-slot="ideas-score"]')).toHaveAttribute("data-tone", "green")
    expect(filterOf(page).sorted).toBeUndefined()

    await page.locator('[data-slot="ideas-score-filter"]').click()
    await page.getByRole("option", { name: "Red (under 40)" }).click()
    await expect.poll(() => filterOf(page)).toMatchObject({ score: "red" })
    await expect(cards(page).first().locator('[data-slot="ideas-score"]')).toHaveAttribute("data-tone", "red")
    await expect(cards(page).locator('[data-slot="ideas-score"]:not([data-tone="red"])')).toHaveCount(0)
  })

  test("an idea's title opens it whole, and New idea writes one", async ({ page }) => {
    await open(page)
    await status(page, "proposed").click()
    const title = (await cards(page).first().locator('[data-slot="ideas-title"]').textContent())!
    await cards(page).filter({ hasText: title }).locator('[data-slot="ideas-title"]').click()
    const whole = drawer(page).locator('[data-slot="ideas-page"]')
    await expect(whole.getByRole("heading", { name: title })).toBeVisible()
    await expect(whole.getByRole("button", { name: "Turn into a ticket" })).toBeVisible()
    await expect(whole.getByRole("button", { name: "Keep", exact: true })).toBeVisible()
    await page.keyboard.press("Escape")

    await page.locator('[data-slot="list-header"]').getByRole("link", { name: "New idea", exact: true }).click()
    await ideaWindow(page).getByLabel("Title").fill("A shop for the mugs")
    await ideaWindow(page).getByRole("button", { name: "Create the idea" }).click()
    await expect(page.getByText("Idea saved: A shop for the mugs")).toBeVisible()
    const mine = cards(page).filter({ hasText: "A shop for the mugs" })
    // Scored behind the form by the light model: "…", then its number.
    await expect(mine.locator('[data-slot="ideas-score"]')).toHaveText("75", { timeout: 15_000 })
    await expect(mine.locator('[data-slot="ideas-score"]')).toHaveAttribute("data-tone", "green")
    await expect(mine).toHaveAttribute("data-author", "human")
    await expect(mine.locator('[data-slot="idea-origin"]')).toHaveText("Workspace")
  })

  test("New idea is a window as tall as its few lines, its title first and its button waiting for one", async ({ page }) => {
    await open(page)
    await page.locator('[data-slot="list-header"]').getByRole("link", { name: "New idea", exact: true }).click()
    const form = ideaWindow(page)
    await expect(form).toBeVisible()
    await expect(form.getByRole("heading", { name: "New idea" })).toBeVisible()
    await expect(form.getByLabel("Title")).toBeFocused()
    await expect(form.getByLabel("Title")).toHaveAttribute("placeholder", "The idea, in one line")
    const box = (await form.boundingBox())!
    expect(box.height).toBeLessThan(600)
    expect(Math.abs(box.y + box.height / 2 - 450)).toBeLessThan(40)

    const create = form.getByRole("button", { name: "Create the idea" })
    await expect(create).toBeDisabled()
    await form.getByLabel("Title").fill("   ")
    await expect(create).toBeDisabled()
    await form.getByLabel("Title").fill("A mug of the month")
    await expect(create).toBeEnabled()

    // The category, as chips; Tech says what it means only once chosen, and lets go when pressed again.
    const tech = form.getByRole("button", { name: "Tech", exact: true })
    const help = form.getByText("Refactoring, performance, technical debt — not a new feature.")
    await expect(help).toHaveCount(0)
    await expect(tech).toHaveAttribute("aria-pressed", "false")
    await tech.click()
    await expect(tech).toHaveAttribute("aria-pressed", "true")
    await expect(help).toBeVisible()
    await form.getByRole("button", { name: "Feature", exact: true }).click()
    await expect(tech).toHaveAttribute("aria-pressed", "false")
    await expect(help).toHaveCount(0)
    await form.getByRole("button", { name: "Feature", exact: true }).click()
    await expect(form.locator('[data-slot="idea-chip"][aria-pressed="true"]')).toHaveCount(0)

    // Escape closes the project menu first, then the window.
    await form.locator('[data-slot="idea-project"]').click()
    await expect(page.getByRole("menuitemradio", { name: "Workspace" })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(page.getByRole("menu")).toHaveCount(0)
    await expect(form).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(form).toHaveCount(0)
    await expect(cards(page).filter({ hasText: "A mug of the month" })).toHaveCount(0)
  })

  test("Ctrl+Enter creates the idea, and Create another empties the window for the next one", async ({ page }) => {
    await open(page)
    await page.locator('[data-slot="list-header"]').getByRole("link", { name: "New idea", exact: true }).click()
    const form = ideaWindow(page)
    await form.getByText("Create another").click()
    await form.getByLabel("Title").fill("A loyalty card")
    await form.getByLabel("Description").fill("Ten coffees, one free.\nOn paper first.")
    await form.getByRole("button", { name: "UX/UI", exact: true }).click()
    await form.getByLabel("Description").press("Control+Enter")
    await expect(page.getByText("Idea saved: A loyalty card")).toBeVisible()
    await expect(form).toBeVisible()
    await expect(form.getByLabel("Title")).toHaveValue("")
    await expect(form.getByLabel("Description")).toHaveValue("")
    await expect(form.locator('[data-slot="idea-chip"][aria-pressed="true"]')).toHaveCount(0)
    await expect(form.getByLabel("Title")).toBeFocused()
    await expect(form.getByRole("checkbox", { name: "Create another" })).toBeChecked()

    // Unticked, the next one closes the window — Enter in the title is enough.
    await form.getByRole("checkbox", { name: "Create another" }).click()
    await form.getByLabel("Title").fill("A gift card")
    await form.getByLabel("Title").press("Enter")
    await expect(page.getByText("Idea saved: A gift card")).toBeVisible()
    await expect(form).toHaveCount(0)
    const loyalty = cards(page).filter({ hasText: "A loyalty card" })
    await expect(loyalty.locator('[data-slot="ideas-category"]')).toHaveAttribute("data-category", "ux")
    await expect(cards(page).filter({ hasText: "A gift card" })).toBeVisible()
  })

  test("the project menu writes the idea for a project, and Propose a new project makes it a project's", async ({ page }) => {
    await open(page)
    await page.locator('[data-slot="list-header"]').getByRole("link", { name: "New idea", exact: true }).click()
    const form = ideaWindow(page)
    const project = form.locator('[data-slot="idea-project"]')
    await expect(project).toHaveText("Workspace")
    await project.click()
    await page.getByRole("menuitemradio", { name: "Website" }).click()
    await expect(project).toHaveText("Website")
    await form.getByLabel("Title").fill("Opening hours on the home page")
    await form.getByRole("button", { name: "Create the idea" }).click()
    await expect(form).toHaveCount(0)
    const forWebsite = cards(page).filter({ hasText: "Opening hours on the home page" })
    await expect(forWebsite.locator('[data-slot="idea-origin"]')).toContainText("Website")

    await page.locator('[data-slot="list-header"]').getByRole("link", { name: "New idea", exact: true }).click()
    await project.click()
    const proposal = page.getByRole("menuitemradio", { name: /Propose a new project/ })
    await expect(proposal).toContainText("The idea becomes a project-creation ticket.")
    await proposal.click()
    await expect(project).toHaveText("New project")
    await form.getByLabel("Title").fill("A shop of its own")
    await form.getByRole("button", { name: "Create the idea" }).click()
    await expect(form).toHaveCount(0)
    const shop = cards(page).filter({ hasText: "A shop of its own" })
    await expect(shop.locator('[data-slot="ideas-kind"]')).toHaveText("New project")
    await expect(shop.getByRole("button", { name: "Create the project" })).toBeVisible()
  })
})

test.describe("at the width of a phone", () => {
  test.use({ viewport: { width: 360, height: 740 } })

  test("the cards stack in one column and stay inside the screen", async ({ page }) => {
    await open(page)
    await expect(cards(page).first()).toBeVisible()
    const box = (await cards(page).first().boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(360)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
  })

  test("New idea is a sheet up from the bottom, its button the whole width and every target a thumb wide", async ({ page }) => {
    await open(page)
    await page.locator('[data-slot="list-header"]').getByRole("link", { name: "New idea", exact: true }).click()
    const form = ideaWindow(page)
    await expect(form.getByLabel("Title")).toBeFocused()
    await expect
      .poll(async () => {
        const box = (await form.boundingBox())!
        return [Math.round(box.x), Math.round(box.width), Math.round(box.y + box.height)]
      })
      .toEqual([0, 360, 740])
    const create = (await form.getByRole("button", { name: "Create the idea" }).boundingBox())!
    expect(create.width).toBeGreaterThan(300)
    for (const target of [
      form.locator('[data-slot="idea-project"]'),
      form.getByRole("button", { name: "Close" }),
      form.locator('[data-slot="idea-chip"]').first(),
      form.getByText("Create another"),
      form.getByRole("button", { name: "Create the idea" }),
    ])
      expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await form.getByRole("button", { name: "Close" }).click()
    await expect(form).toHaveCount(0)
  })
})
