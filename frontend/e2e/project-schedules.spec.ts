import { expect, test, type Page } from "@playwright/test"

/* What a project's page says besides its tickets: the schedules whose tickets
 * are for it, in a tab of their own; the goals it serves, with how far they
 * have gone; and, for a project the configuration alone names, why there is no
 * "New ticket" and where its page is made.
 *
 * The schedules and the goals are answered by the test, over the board's own:
 * the board is shared, and a schedule or a goal more is one more row for
 * another test to count.
 */

const WEBSITE = "0000000000000000000000000000cafe"
const PAGE = `/?view=console/projects/read/${WEBSITE}`

async function signIn(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
}

/** The board's schedules, one of them said to be Website's. */
async function oneForWebsite(page: Page) {
  await page.route(/\/api\/schedules$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    try {
      const response = await route.fetch()
      const body = await response.json()
      const schedules = body.schedules.map((schedule: { name: string }) =>
        schedule.name === "Weekly digest" ? { ...schedule, project: "Website", project_id: WEBSITE } : schedule
      )
      await route.fulfill({ response, json: { ...body, schedules } })
    } catch {
      // Read again once more, still on its way when the test ends.
    }
  })
}

test.use({ viewport: { width: 1440, height: 900 } })

test("the schedules tab lists the project's, and a new one is for the project", async ({ page }) => {
  await oneForWebsite(page)
  const sent: Record<string, unknown>[] = []
  await page.route(/\/api\/schedules$/, async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "new0000", name: "Revue", url: "" } })
  })
  await signIn(page)
  await page.goto(`${PAGE}&tab=schedules`)
  const tab = page.getByRole("tab", { name: "Schedules", exact: true })
  await expect(tab).toHaveAttribute("aria-selected", "true")
  const panel = page.getByRole("tabpanel", { name: "Schedules" })
  await expect(panel.getByRole("link", { name: "Weekly digest" })).toBeVisible()
  await expect(panel.getByText("Test email")).toHaveCount(0)

  await panel.getByText("New schedule").click()
  const window_ = page.getByRole("dialog")
  await expect(window_.getByRole("combobox", { name: "Project" })).toContainText("Website")
  await window_.getByLabel("Ticket title").fill("Revue")
  await window_.getByRole("button", { name: "Create the schedule" }).click()
  await expect(window_).not.toBeAttached()
  expect(sent[0]).toMatchObject({ name: "Revue", project: WEBSITE })
  // Back on the project's page, on the same tab.
  await expect(page).toHaveURL(/projects\/read/)
  await expect(tab).toHaveAttribute("aria-selected", "true")
})

test("the tab is written in the address, as the others are", async ({ page }) => {
  await oneForWebsite(page)
  await signIn(page)
  await page.goto(PAGE)
  await page.getByRole("tab", { name: "Schedules", exact: true }).click()
  await expect(page).toHaveURL(/tab=schedules/)
  await page.reload()
  await expect(page.getByRole("tab", { name: "Schedules", exact: true })).toHaveAttribute("aria-selected", "true")
})

test("the active goals of the project are on its page, with their progress", async ({ page }) => {
  await page.route(/\/api\/goals$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const goal = { url: "", description: "", criterion: "", due: "", status: "", priority: null, project_ids: [WEBSITE] }
    await route.fulfill({
      json: {
        configured: true,
        goals: [
          { ...goal, id: "g1", name: "Ship the site", active: true, projects: ["Website"], tickets: { done: 1, ready: 2 } },
          { ...goal, id: "g2", name: "An old one", active: false, status: "Done", projects: ["Website"], tickets: {} },
          { ...goal, id: "g3", name: "Someone else's", active: true, projects: ["Journal"], tickets: {} },
        ],
      },
    })
  })
  await signIn(page)
  await page.goto(PAGE)
  const goals = page.locator('[data-slot="project-goals"]')
  await expect(goals.getByRole("link", { name: "Ship the site" })).toBeVisible()
  await expect(goals.getByRole("progressbar", { name: "1 of 3 tickets done" })).toBeVisible()
  await expect(goals.getByText("An old one")).toHaveCount(0)
  await expect(goals.getByText("Someone else's")).toHaveCount(0)
  await goals.locator('[data-slot="project-goals-all"]').click()
  await expect(page).toHaveURL(/goals\/list/)
  expect(decodeURIComponent(page.url())).toContain('"project":"Website"')
})

test("a project of the configuration says why it has no New ticket, and has no schedules tab", async ({ page }) => {
  await page.route(/\/api\/projects$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const response = await route.fetch()
    const body = await response.json()
    const line = { id: "", name: "Atelier", kind: "code", url: "", repository: "", path: "/srv/atelier", configured: "/srv/atelier", source: "config" }
    await route.fulfill({ response, json: { ...body, projects: [...body.projects, line] } })
  })
  await signIn(page)
  await page.goto("/?view=console/projects/read/config:Atelier&tab=schedules")
  await expect(page.getByRole("heading", { name: "Atelier" })).toBeVisible()
  await expect(page.getByRole("tab", { name: "Tickets", exact: true })).toHaveAttribute("aria-selected", "true")
  await expect(page.getByRole("tab", { name: "Schedules", exact: true })).toHaveCount(0)
  const said = page.locator('[data-slot="project-no-page"]')
  await expect(said).toContainText("This project has no page: create it to attach tickets to it.")
  await said.getByRole("link", { name: "Create its page" }).click()
  const window_ = page.getByRole("dialog")
  await expect(window_.getByRole("textbox", { name: /^Name/ })).toHaveValue("Atelier")
  // Its own name is not one already taken: the page made is that project's.
  await expect(window_.locator('[data-slot="project-name-taken"]')).toHaveCount(0)
})

test("a schedule opened from the tab keeps the tab behind its window, and its trash stays on the page", async ({ page }) => {
  await oneForWebsite(page)
  // Answered here: the board is shared, and the schedule stays on it for the others.
  const deleted: string[] = []
  await page.route(/\/api\/schedules\/[0-9a-f]+\/delete$/, async (route) => {
    deleted.push(route.request().url())
    await route.fulfill({ json: { id: "x", name: "Weekly digest" } })
  })
  await signIn(page)
  await page.goto(`${PAGE}&tab=schedules`)
  const tab = page.getByRole("tab", { name: "Schedules", exact: true })
  const panel = page.getByRole("tabpanel", { name: "Schedules" })
  await panel.getByRole("link", { name: "Weekly digest" }).click()
  const window_ = page.getByRole("dialog")
  await expect(window_).toBeVisible()
  await expect(page).toHaveURL(/tab=schedules/)
  await page.keyboard.press("Escape")
  await expect(window_).not.toBeAttached()
  await expect(tab).toHaveAttribute("aria-selected", "true")

  await panel.locator('[data-slot="table-row"]', { hasText: "Weekly digest" }).locator("[data-delete-schedule]").click()
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete the schedule" }).click()
  await expect(page.getByText("Schedule “Weekly digest” deleted")).toBeVisible()
  expect(deleted).toHaveLength(1)
  await expect(page).toHaveURL(/projects\/read/)
  await expect(tab).toHaveAttribute("aria-selected", "true")
})
