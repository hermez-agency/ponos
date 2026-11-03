import { expect, test, type Page } from "@playwright/test"

/* Finding a project in the list: the words of its name, its type, both — and
 * the address that keeps them.
 *
 * The search is react-resource-view's own filter bar, so what is held here is
 * what it writes in the address and what the list does with it: a link shared
 * or a reload opens the same list.
 */

const LIST = "/?view=console/projects/list&variant=cards"

const card = (page: Page, name: string) => page.locator("[data-project-card]", { hasText: name })
const search = (page: Page) => page.getByPlaceholder("Search a project")

async function open(page: Page, path = LIST) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  await expect(card(page, "Website")).toBeVisible()
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("a part of a name keeps the projects that have it, whatever the case", async ({ page }) => {
    await open(page)
    await search(page).fill("NEWS")
    await expect(card(page, "Newsletter")).toBeVisible()
    await expect(card(page, "Website")).toHaveCount(0)
    await expect(card(page, "Journal")).toHaveCount(0)
  })

  test("the type keeps the projects of that type", async ({ page }) => {
    await open(page)
    await page.locator("[data-slot=projects-type-filter]").click()
    await page.getByRole("option", { name: "document work" }).click()
    await expect(card(page, "Journal")).toBeVisible()
    await expect(card(page, "Website")).toHaveCount(0)
  })

  test("the words and the type are combined", async ({ page }) => {
    await open(page)
    await search(page).fill("e")
    await page.locator("[data-slot=projects-type-filter]").click()
    await page.getByRole("option", { name: "code work" }).click()
    await expect(card(page, "Website")).toBeVisible()
    await expect(card(page, "Newsletter")).toBeVisible()
    await expect(card(page, "Journal")).toHaveCount(0)
    await search(page).fill("journal")
    await expect(page.getByText("No project matches")).toBeVisible()
  })

  test("a list with nothing to show says so, and the button brings the projects back", async ({ page }) => {
    await open(page)
    await search(page).fill("zzz")
    await expect(page.getByText("No project matches")).toBeVisible()
    await page.getByRole("button", { name: "Clear the search" }).last().click()
    await expect(card(page, "Website")).toBeVisible()
    await expect(search(page)).toHaveValue("")
    await expect(page.getByText("No project matches")).toHaveCount(0)
  })

  test("the search is in the address, and a reload opens the same list", async ({ page }) => {
    await open(page)
    await search(page).fill("news")
    await expect(card(page, "Website")).toHaveCount(0)
    expect(new URL(page.url()).searchParams.get("filter")).toContain("news")
    const address = page.url()
    await page.reload()
    await expect(card(page, "Newsletter")).toBeVisible()
    await expect(card(page, "Website")).toHaveCount(0)
    await expect(search(page)).toHaveValue("news")
    await page.goto(address)
    await expect(card(page, "Newsletter")).toBeVisible()
  })
})

test.describe("at 390px", () => {
  test.use({ viewport: { width: 390, height: 800 } })

  test("the search is there on a phone, and finds a project", async ({ page }) => {
    await open(page)
    await search(page).fill("jour")
    await expect(card(page, "Journal")).toBeVisible()
    await expect(card(page, "Website")).toHaveCount(0)
  })
})
