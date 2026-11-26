import { expect, test, type Page } from "@playwright/test"

/* Archiving a project puts it away without losing anything.
 *
 * From its card's “…”: the card leaves the list as it rests, the « Archived »
 * filter brings it back with its badge, its ticket is still on the board, and
 * « Unarchive » from the same menu puts everything as it was. On the console
 * given `doomed`, whose « Old wiki » no other test touches.
 */

const LIST = "/?view=console/projects/list&variant=cards"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await expect(page.getByText("Website").first()).toBeVisible()
}

const card = (page: Page, name: string) => page.locator("[data-project-card]", { hasText: name })
const menu = (page: Page, name: string) => page.getByRole("button", { name: `More actions on “${name}”` })
const filter = (page: Page) => page.locator('[data-slot="projects-archived-filter"]')

async function shelved(page: Page, name: string) {
  const read = await (await page.request.get("/api/projects")).json()
  return read.projects.find((project: { name: string }) => project.name === name)?.shelved ?? false
}

test.use({ viewport: { width: 1440, height: 900 } })

test("a project is archived, shown again by the filter, and unarchived", async ({ page }) => {
  await open(page)
  await expect(card(page, "Old wiki")).toBeVisible()
  // Nothing archived yet: no filter to offer.
  await expect(filter(page)).toHaveCount(0)

  await menu(page, "Old wiki").click()
  await page.getByRole("menuitem", { name: "Archive" }).click()
  await expect(page.getByText("Project “Old wiki” archived")).toBeVisible()
  await expect(card(page, "Old wiki")).toHaveCount(0)
  await expect(card(page, "Website")).toBeVisible()
  expect(await shelved(page, "Old wiki")).toBe(true)

  // The filter counts it, and shows it with its badge.
  await expect(filter(page)).toContainText("1")
  await expect(filter(page)).toHaveAttribute("aria-pressed", "false")
  await filter(page).click()
  await expect(filter(page)).toHaveAttribute("aria-pressed", "true")
  await expect(card(page, "Old wiki")).toBeVisible()
  await expect(card(page, "Old wiki").locator('[data-slot="project-archived"]')).toBeVisible()
  await expect(card(page, "Website").locator('[data-slot="project-archived"]')).toHaveCount(0)

  // Nothing is lost: its ticket is still on the board, still ready.
  const board = await (await page.request.get("/api/board")).json()
  const ticket = board.tickets.find((one: { title: string }) => one.title === "Old wiki work, ready")
  expect(ticket?.column).toBe("ready")

  await menu(page, "Old wiki").click()
  await page.getByRole("menuitem", { name: "Unarchive" }).click()
  await expect(page.getByText("Project “Old wiki” unarchived")).toBeVisible()
  await expect(card(page, "Old wiki").locator('[data-slot="project-archived"]')).toHaveCount(0)
  expect(await shelved(page, "Old wiki")).toBe(false)

  // The filter off again, the list rests as before.
  await filter(page).click()
  await expect(filter(page)).toHaveCount(0)
  await expect(card(page, "Old wiki")).toBeVisible()
})
