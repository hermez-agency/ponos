import { expect, test, type Page } from "@playwright/test"

/* Deleting a project asks for a tick, and then it is gone at once.
 *
 * From the list and from the project's own page, through the same dialog. What
 * is tested is the way a person goes: the menu, the dialog that names the
 * project and counts its tickets, a button that stays off until the box is
 * ticked, and — once it is — the card gone from the list and the ticket the
 * runner could have taken blocked, without waiting for any synchronisation.
 */

const LIST = "/?view=console/projects/list&variant=cards"

async function open(page: Page, path = LIST) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  await expect(page.getByText("Website").first()).toBeVisible()
}

const card = (page: Page, name: string) => page.locator("[data-project-card]", { hasText: name })
const menu = (page: Page, name: string) => page.getByRole("button", { name: `More actions on “${name}”` })
const dialog = (page: Page) => page.locator("[data-delete-project]")
const confirm = (page: Page) => dialog(page).getByRole("button", { name: "Delete the project" })

async function statusOf(page: Page, title: string) {
  const board = await (await page.request.get("/api/board")).json()
  return board.tickets.find((ticket: { title: string }) => ticket.title === title)?.column
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("a project is deleted from the list, once the box is ticked", async ({ page }) => {
    await open(page)
    await menu(page, "Old shop").click()
    await page.getByRole("menuitem", { name: "Delete" }).click()

    // It names the project, counts its tickets, and says what happens.
    await expect(dialog(page)).toBeVisible()
    await expect(dialog(page).getByRole("heading", { name: "Delete “Old shop”?" })).toBeVisible()
    await expect(dialog(page)).toContainText("2 tickets point at it")
    await expect(dialog(page)).toContainText("never deleted")
    await expect(confirm(page)).toBeDisabled()

    // Without the tick, Enter deletes nothing.
    const sure = dialog(page).getByRole("checkbox", { name: "Yes, I am sure I want to delete this project" })
    await expect(sure).not.toBeChecked()
    await page.keyboard.press("Enter")
    await expect(dialog(page)).toBeVisible()
    expect(await statusOf(page, "Old shop work, ready")).toBe("ready")

    // Once ticked, the button is on and Enter deletes.
    await sure.check()
    await expect(confirm(page)).toBeEnabled()
    await expect(confirm(page).locator("kbd")).toHaveText("↵ Enter")
    await page.keyboard.press("Enter")

    await expect(dialog(page)).toBeHidden()
    await expect(page.getByText("Project “Old shop” deleted")).toBeVisible()
    await expect(card(page, "Old shop")).toHaveCount(0)
    await expect(card(page, "Old blog")).toBeVisible()
    // Its ticket the runner could have taken is stopped; the finished one is not touched.
    await expect.poll(() => statusOf(page, "Old shop work, ready")).toBe("blocked")
    expect(await statusOf(page, "Old shop work, done")).toBe("done")
    const projects = await (await page.request.get("/api/projects")).json()
    expect(projects.projects.map((project: { name: string }) => project.name)).not.toContain("Old shop")
  })

  test("the page of a project has the same action, beside Edit", async ({ page }) => {
    await open(page)
    await card(page, "Old blog").click()
    await expect(page.getByRole("heading", { name: "Old blog" })).toBeVisible()
    await expect(page.getByRole("link", { name: "Edit" })).toBeVisible()

    await menu(page, "Old blog").click()
    await page.getByRole("menuitem", { name: "Delete" }).click()
    await dialog(page).getByRole("checkbox", { name: /Also delete its/ }).check()
    await dialog(page).getByRole("checkbox", { name: "Yes, I am sure I want to delete this project" }).check()
    await confirm(page).click()

    // Back on the list, where it is no longer.
    await expect(page).toHaveURL(/view=console\/projects\/list/)
    await expect(card(page, "Website")).toBeVisible()
    await expect(card(page, "Old blog")).toHaveCount(0)
    await expect(page.getByText("Project “Old blog” deleted")).toBeVisible()
    // And, as asked, its tickets are out of the board with it.
    await expect.poll(() => statusOf(page, "Old blog work, ready")).toBeUndefined()
    expect(await statusOf(page, "Old blog work, done")).toBeUndefined()
  })
})
