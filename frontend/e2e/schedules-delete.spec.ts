import { expect, test, type Page } from "@playwright/test"

/* Deleting a schedule, in French, from the list and from the calendar.
 *
 * The console is shared by every spec and its two schedules are counted by the
 * others, so the deletion itself is answered by the test, as the creation is in
 * `schedule-window.spec.ts`: what is checked here is the gesture — the
 * confirmation first, then the request, then the row gone from the list. The
 * board's side (the page goes to the trash, the pass stops reading it) is
 * `a_schedule_deleted_from_the_console_...` in the core's suite.
 */

const LIST = "/?view=console/schedules/list"

test.use({ locale: "fr-FR" })

async function open(page: Page, url = LIST) {
  const deleted: string[] = []
  await page.route(/\/api\/schedules\/[0-9a-f]+\/delete$/, async (route) => {
    const id = route.request().url().split("/").at(-2)!
    deleted.push(id)
    await route.fulfill({ json: { id, name: "Test email" } })
  })
  await page.route(/\/api\/schedules$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    try {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: { ...body, schedules: body.schedules.filter((one: { id: string }) => !deleted.includes(one.id)) },
      })
    } catch {
      // The list read again after the deletion, still on its way when the test ends.
    }
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(url)
  await expect(page.getByText("Test email").first()).toBeVisible()
  return deleted
}

test("the trash can asks first, and the schedule leaves the list", async ({ page }) => {
  const deleted = await open(page)
  const row = page.locator("tr", { hasText: "Test email" })
  await row.getByRole("button", { name: /Supprimer la récurrence/ }).click()
  const dialog = page.getByRole("alertdialog")
  await expect(dialog).toContainText("Supprimer « Test email » ?")
  await expect(dialog).toContainText("Les tickets déjà créés restent en place")
  expect(deleted, "nothing is sent before the confirmation").toEqual([])
  await dialog.getByRole("button", { name: "Annuler" }).click()
  await expect(row).toBeVisible()
  expect(deleted).toEqual([])

  await row.getByRole("button", { name: /Supprimer la récurrence/ }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: /Supprimer la récurrence/ }).click()
  await expect(page.locator("tr", { hasText: "Test email" })).toHaveCount(0)
  await expect(page.locator("tr", { hasText: "Weekly digest" })).toBeVisible()
  expect(deleted).toHaveLength(1)
})

test("the calendar has it too, in the window of a launch", async ({ page }) => {
  const deleted = await open(page)
  await page.getByRole("tab", { name: "Calendrier" }).click()
  await page.getByText("Test email").first().click()
  await page.getByRole("button", { name: /Supprimer la récurrence/ }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: /Supprimer la récurrence/ }).click()
  await expect.poll(() => deleted.length).toBe(1)
})
