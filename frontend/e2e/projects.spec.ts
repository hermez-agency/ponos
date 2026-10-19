import { expect, test, type Page } from "@playwright/test"

/* A project in the list is a link to its page, the whole card of it.
 *
 * It was a name to click on a card most of which did nothing, and a button
 * under it to open the page. What is tested is the way a user goes: a click
 * anywhere on the card, a middle click for a tab, Tab then Enter — and, from
 * the page, the form in a drawer, a field changed, Save.
 */

const LIST = "/?view=console/projects/list&variant=cards"

async function open(page: Page, path = LIST) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  await expect(page.getByText("Website").first()).toBeVisible()
}

const card = (page: Page, name: string) => page.locator("[data-project-card]", { hasText: name })
const drawer = (page: Page) => page.locator('[data-slot="drawer-popup"]')

/** The page of a project: its address, and its name in the header. */
async function onThePageOf(page: Page, name: string) {
  await expect(page).toHaveURL(/view=console\/projects\/read/)
  await expect(page.getByRole("heading", { name })).toBeVisible()
}

async function openWebsiteForm(page: Page) {
  await card(page, "Website").click()
  await onThePageOf(page, "Website")
  await page.getByRole("link", { name: "Edit" }).click()
  await expect(drawer(page)).toBeVisible()
  await expect(drawer(page).getByRole("textbox", { name: /^Name/ })).toHaveValue("Website")
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("a click anywhere on a card opens the project's page", async ({ page }) => {
    await open(page)
    const box = (await card(page, "Website").boundingBox())!
    // The bottom right corner: neither the name nor the picture.
    await page.mouse.click(box.x + box.width - 12, box.y + box.height - 12)
    await onThePageOf(page, "Website")
  })

  test("a card is a real link: a middle click opens the project in a tab", async ({ page }) => {
    await open(page)
    await expect(card(page, "Website")).toHaveAttribute("href", /projects\/read/)
    const [tab] = await Promise.all([
      page.context().waitForEvent("page"),
      card(page, "Website").click({ button: "middle" }),
    ])
    await tab.waitForLoadState()
    expect(tab.url()).toMatch(/projects\/read/)
    // And the list stays where it was.
    expect(new URL(page.url()).searchParams.get("view")).toBe("console/projects/list")
  })

  test("a card is reached from the keyboard, and Enter opens it", async ({ page }) => {
    await open(page)
    await card(page, "Journal").focus()
    await expect(card(page, "Journal")).toBeFocused()
    await page.keyboard.press("Enter")
    await onThePageOf(page, "Journal")
  })

  test("a card says its kind, its repository and its tickets, and has no button under it", async ({ page }) => {
    await open(page)
    const website = card(page, "Website")
    await expect(website.getByText("Code", { exact: true })).toBeVisible()
    await expect(website.getByText("example/website")).toBeVisible()
    // No path is set: nothing is said about where the clone is.
    await expect(website.getByText("wherever the clone is")).toHaveCount(0)
    await expect(page.getByRole("button", { name: "Open", exact: true })).toHaveCount(0)
    await expect(page.locator("[data-project-card] button, [data-project-card] a")).toHaveCount(0)
    await expect(page.getByRole("link", { name: "Open", exact: true })).toHaveCount(0)
    for (const name of ["Website", "Newsletter", "Journal"])
      await expect(card(page, name).getByText(/\d+ tickets?/)).toBeVisible()
  })

  test("“+ Ticket” on a card opens a new ticket for that project, and not the project", async ({ page }) => {
    await open(page)
    const sent: Record<string, unknown>[] = []
    await page.route("**/api/tickets", async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      sent.push(route.request().postDataJSON())
      await route.fulfill({ json: { id: "0000000000000000000000000000f0aa", title: "From a card" } })
    })
    // One with no repository too: its tickets come back as a document.
    await card(page, "Journal").locator("xpath=..").locator("[data-project-new-ticket]").click()
    // Over the projects, not the project's page: the address names the list, then the form.
    expect(new URL(page.url()).searchParams.get("view")).toBe("console/projects/list/tickets/create")
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByRole("combobox", { name: "Project" })).toContainText("Journal")
    await dialog.getByLabel("Title").fill("From a card")
    await dialog.getByRole("button", { name: "Launch the ticket" }).click()
    await expect.poll(() => sent.length).toBe(1)
    expect(sent[0]).toMatchObject({ title: "From a card", type: "" })
    expect(sent[0].project).toBeTruthy()
  })

  test("a project without a repository says it in one line, behind its own icon", async ({ page }) => {
    await open(page)
    const journal = card(page, "Journal")
    await expect(journal.getByText("Writing", { exact: true })).toBeVisible()
    await expect(journal.getByText("Produces documents")).toBeVisible()
    await expect(journal.getByText("📝")).toBeVisible()
  })

  test("the cards of a row are as tall as each other", async ({ page }) => {
    await open(page)
    const heights = await page
      .locator("[data-project-card]")
      .evaluateAll((cards) => cards.map((one) => Math.round(one.getBoundingClientRect().height)))
    expect(heights.length).toBe(3)
    expect(new Set(heights).size).toBe(1)
  })

  test("a row of the table opens the project's page, wherever it is clicked", async ({ page }) => {
    await open(page, `${LIST}&variant=table`)
    const row = page.locator("[data-project-row]", { hasText: "Website" })
    await expect(row).toHaveAttribute("href", /projects\/read/)
    const box = (await row.boundingBox())!
    // Short of “+ Ticket” and the “…” menu, which are the two places on the row that are not the link.
    await page.mouse.click(box.x + box.width - 130, box.y + box.height / 2)
    await onThePageOf(page, "Website")
  })

  test("the form opens in a drawer from the project's page", async ({ page }) => {
    await open(page)
    await openWebsiteForm(page)
    // The brief is read too: the drawer asks for the project.
    await expect(drawer(page).getByText("The brief of Website.")).toBeVisible()
    // A link to the page it is opened from would be a link to where you are.
    await expect(drawer(page).getByRole("link", { name: "Open the project's page" })).toHaveCount(0)
    await expect.poll(async () => Math.round((await drawer(page).boundingBox())?.width ?? 0)).toBe(640)
  })

  test("Escape, the cross and a click beside it close the drawer", async ({ page }) => {
    await open(page)
    await openWebsiteForm(page)
    await page.keyboard.press("Escape")
    await expect(drawer(page)).toBeHidden()

    await page.getByRole("link", { name: "Edit" }).click()
    await expect(drawer(page)).toBeVisible()
    await drawer(page).locator('[data-slot="drawer-close"]').click()
    await expect(drawer(page)).toBeHidden()

    await page.getByRole("link", { name: "Edit" }).click()
    await expect(drawer(page)).toBeVisible()
    await page.mouse.click(20, 450)
    await expect(drawer(page)).toBeHidden()
  })

  test("a save closes the drawer, and the list says the new name", async ({ page }) => {
    await open(page)
    await card(page, "Newsletter").click()
    await onThePageOf(page, "Newsletter")
    await page.getByRole("link", { name: "Edit" }).click()
    const name = drawer(page).getByRole("textbox", { name: /^Name/ })
    await expect(name).toHaveValue("Newsletter")
    await name.fill("Weekly letter")
    await drawer(page).getByRole("button", { name: "Save" }).click()
    await expect(drawer(page)).toBeHidden()
    await page.goBack()
    await expect(card(page, "Weekly letter")).toBeVisible()
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("the drawer takes the whole screen", async ({ page }) => {
    await open(page)
    await openWebsiteForm(page)
    await expect
      .poll(async () => {
        const box = await drawer(page).boundingBox()
        return box && [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)]
      })
      .toEqual([0, 0, 390, 844])
  })
})

test.describe("the statistics of a project", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("the page asks for its own project, folds, and keeps to the phone's width", async ({ page }) => {
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    const band = page.locator('[data-slot="statistics-band"]')
    await expect(band.getByRole("tab", { name: "7 days" })).toHaveAttribute("aria-selected", "true")

    const asked = page.waitForRequest(
      (request) => request.url().includes("/api/statistics") && request.url().includes("project=Website")
    )
    await band.getByRole("tab", { name: "30 days" }).click()
    expect(new URL((await asked).url()).searchParams.get("project")).toBe("Website")

    // The e2e board has no ticket of this project in the period: the empty state, not zeroed charts.
    await expect(band.getByText("No ticket of this project over this period.")).toBeVisible()
    await expect(band.getByText("Created, by project", { exact: true })).toHaveCount(0)
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, "no sideways scroll").toBeLessThanOrEqual(390)

    await band.getByRole("button", { name: /Statistics/ }).click()
    await expect(band.getByText("No ticket of this project over this period.")).toBeHidden()
  })
})

test.describe("the blocks of a project", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("are folded behind Show more on its page, as on the dashboard", async ({ page }) => {
    // The e2e board has no ticket of this project: give the page figures to draw.
    await page.route("**/api/statistics*", async (route) => {
      const answer = await route.fetch()
      const figures = await answer.json()
      figures.totals = { ...figures.totals, created: 2, closed: 1 }
      await route.fulfill({ response: answer, json: figures })
    })
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    const band = page.locator('[data-slot="statistics-band"]')
    const panel = band.getByText("Blocks, by cause and week", { exact: true })
    await expect(band.getByText("Activity", { exact: true })).toBeVisible()
    await expect(panel).toHaveCount(0)

    await band.getByRole("button", { name: "Show more", exact: true }).click()
    await expect(panel.first()).toBeVisible()
    await page.reload()
    await expect(band.getByRole("button", { name: "Show less", exact: true })).toBeVisible()
    await expect(panel.first()).toBeVisible()

    await band.getByRole("button", { name: "Show less", exact: true }).click()
    await expect(panel).toHaveCount(0)
  })
})

test.describe("the page of a project", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  const tab = (page: Page, name: string) => page.getByRole("tab", { name, exact: true })

  test("opens on the tickets, and the tab picked survives a reload", async ({ page }) => {
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    await expect(tab(page, "Tickets")).toHaveAttribute("aria-selected", "true")

    await tab(page, "Brief").click()
    await expect(page.getByText("The brief of Website.")).toBeVisible()
    await expect(page).toHaveURL(/tab=brief/)

    await page.reload()
    await expect(tab(page, "Brief")).toHaveAttribute("aria-selected", "true")
    await expect(page.getByText("The brief of Website.")).toBeVisible()

    await tab(page, "Tickets").click()
    await expect(page).toHaveURL(/tab=tickets/)
  })

  test("the brief is edited in place, saved with Ctrl+S, and guarded while unsaved", async ({ page }) => {
    await open(page, "/?view=console/projects/read/0000000000000000000000000000cafe&tab=brief")
    await onThePageOf(page, "Website")
    const edit = page.getByRole("tabpanel", { name: "Brief" }).getByRole("button", { name: "Edit" })
    await edit.click()
    const editor = page.locator('[data-slot="project-brief-editor"]')
    await expect(editor).toBeVisible()
    const save = editor.getByRole("button", { name: "Save", exact: true })
    await expect(save).toBeDisabled()

    // Nothing changed: Escape leaves.
    await page.keyboard.press("Escape")
    await expect(editor).toBeHidden()
    await edit.click()

    await editor.locator(".ProseMirror").click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type(" Always in French.")
    await expect(editor.getByText("Unsaved changes")).toBeVisible()

    // Leaving the tab with something typed asks first, and staying keeps it.
    await tab(page, "Tickets").click()
    await expect(page.getByRole("alertdialog")).toBeVisible()
    await page.getByRole("button", { name: "Keep editing" }).click()
    await expect(editor).toBeVisible()

    await page.keyboard.press("Control+s")
    await expect(page.getByText("The brief is saved")).toBeVisible()
    await expect(editor).toBeHidden()
    await expect(page.getByText("Always in French.")).toBeVisible()

    // And it was written to the board, not just drawn.
    await page.reload()
    await expect(page.getByText("Always in French.")).toBeVisible()
  })

  test("a ticket made from the tickets tab is in its list, for this project", async ({ page }) => {
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    await page.getByRole("link", { name: "New ticket" }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    // The project is the page's: the form comes with it settled.
    await expect(dialog.getByRole("group").filter({ hasText: "Project" }).getByRole("combobox")).toContainText("Website")
    await dialog.getByLabel("Title").fill("Fix the footer of the site")
    await dialog.getByRole("button", { name: "Launch the ticket" }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText("Fix the footer of the site").filter({ visible: true }).first()).toBeVisible()
  })

  test("the tickets are the dashboard's list, in a board and in a table, kept to the project", async ({ page }) => {
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    // The board is shared with the other tests: this one brings its own ticket.
    await page.getByRole("link", { name: "New ticket" }).click()
    const dialog = page.getByRole("dialog")
    await dialog.getByLabel("Title").fill("Rows of the table")
    await dialog.getByRole("button", { name: "Launch the ticket" }).click()
    await expect(dialog).toBeHidden()
    const layouts = page.getByRole("tablist").filter({ hasText: "table" })
    await expect(layouts).toBeVisible()

    await layouts.getByRole("tab", { name: "table" }).click()
    const heads = page.getByRole("columnheader")
    for (const name of ["Id", "Ticket", "Status", "Priority", "Type", "Cost", "Last modified"])
      await expect(heads.filter({ hasText: name }).first()).toBeVisible()
    // The address stays the project's: the layout is remembered, not navigated to.
    await expect(page).toHaveURL(/projects\/read/)

    // Nothing of another project, and the layout is the dashboard's next time.
    await expect(page.locator('[data-slot="table-row"]', { hasText: "Elsewhere" })).toHaveCount(0)
    await page.getByRole("link", { name: /^Dashboard/ }).click()
    await expect(page).toHaveURL(/variant=table/)
  })

  test("the page takes the width the dashboard does, tickets and brief alike", async ({ page }) => {
    const content = page.locator('[data-slot="admin-content"]')
    const widthOf = async () => Math.round((await content.boundingBox())!.width)
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    await expect(content).toHaveAttribute("data-full-width", "true")
    const project = await widthOf()
    await tab(page, "Brief").click()
    await expect(page.getByText("The brief of Website.")).toBeVisible()
    expect(await widthOf()).toBe(project)

    await page.goto("/?view=console/tickets/list")
    await expect(content).toHaveAttribute("data-full-width", "true")
    expect(await widthOf()).toBe(project)
  })

  test("a project with no clone says so, rather than saying where a clone would be", async ({ page }) => {
    await open(page)
    await card(page, "Website").click()
    await onThePageOf(page, "Website")
    await expect(page.getByText("Not cloned on this machine yet")).toBeVisible()
    await expect(page.getByText("wherever the clone is")).toHaveCount(0)
  })
})

test.describe("the settings of a project", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  // Website rather than Newsletter: another test renames Newsletter meanwhile.
  const WEBSITE = "/?view=console/projects/read/0000000000000000000000000000cafe"
  const own = (page: Page) => page.getByRole("switch", { name: "Its own automatic validation" })
  const code = (page: Page) => page.getByRole("switch", { name: "Code tickets" })
  // `open` waits for Website, which neither of these pages names.
  const go = async (page: Page, path: string) => {
    await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
    await page.goto(path)
  }

  test("follow the global switches until the project has its own, which outlive a reload", async ({ page }) => {
    await go(page, `${WEBSITE}&tab=settings`)
    await onThePageOf(page, "Website")
    await expect(page.getByRole("tab", { name: "Settings", exact: true })).toHaveAttribute("aria-selected", "true")

    // Off: the four global switches, as they stand, and the way to change them.
    await expect(own(page)).toHaveAttribute("aria-checked", "false")
    await expect(page.getByText("Off: this project follows the global settings.")).toBeVisible()
    for (const label of ["Code tickets", "Publication tickets", "Writing tickets", "External action tickets"])
      await expect(page.getByRole("switch", { name: label })).toBeDisabled()
    await expect(code(page)).toHaveAttribute("aria-checked", "false")
    await expect(page.getByRole("link", { name: "Change them in the global settings" })).toBeVisible()
    // The same « ? » as the global card, with the same sentence behind it.
    await page.getByRole("button", { name: "More about “Code tickets”" }).click()
    await expect(page.getByText("A merge GitHub refuses leaves the ticket in review")).toBeVisible()
    await page.keyboard.press("Escape")

    // On: started from the global values, then a switch of its own.
    await own(page).click()
    await expect(own(page)).toHaveAttribute("aria-checked", "true")
    await expect(code(page)).toBeEnabled()
    await expect(code(page)).toHaveAttribute("aria-checked", "false")
    await code(page).click()
    await expect(code(page)).toHaveAttribute("aria-checked", "true")

    await page.reload()
    await expect(own(page)).toHaveAttribute("aria-checked", "true")
    await expect(code(page)).toHaveAttribute("aria-checked", "true")

    // The global card names it, and leads back to it.
    await go(page, "/?view=console/settings/read/config/execution")
    const line = page.locator('[data-slot="own-validation"]')
    await expect(line).toContainText("A project can have its own automatic validation")
    await line.getByRole("link", { name: "Website" }).click()
    await onThePageOf(page, "Website")
    await expect(own(page)).toHaveAttribute("aria-checked", "true")

    // Off again: the global switch shows, and the project's is forgotten.
    await own(page).click()
    await expect(own(page)).toHaveAttribute("aria-checked", "false")
    await expect(code(page)).toHaveAttribute("aria-checked", "false")
    await expect(code(page)).toBeDisabled()
  })
})
