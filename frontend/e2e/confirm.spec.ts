import { expect, test, type Page } from "@playwright/test"

/* Every confirmation answers the keyboard the same way.
 *
 * They all go through one window: the focus opens on the main button, Enter
 * does the main thing, Escape cancels, and a badge in each button says so. Tried
 * on the run-again window of a Done ticket; the deletion of a project, whose
 * main button waits for a name, is tried in `project-delete.spec.ts`.
 */

const DONE = "0000000000000000000000000000d0e0"

async function open(page: Page, path: string) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const dialog = (page: Page) => page.getByRole("alertdialog")

async function asking(page: Page) {
  await open(page, `/?view=console/tickets/read/${DONE}`)
  await page.getByRole("button", { name: "More actions" }).click()
  await page.getByRole("menuitem", { name: "Run again" }).click()
  await expect(dialog(page)).toBeVisible()
}

test.use({ viewport: { width: 1440, height: 900 } })

test("the focus opens on the main button, and the badges name both keys", async ({ page }) => {
  await asking(page)
  await expect(dialog(page).getByRole("button", { name: "Run it again" })).toBeFocused()
  await expect(dialog(page).getByRole("button", { name: "Cancel" }).locator("kbd")).toHaveText("Esc")
  await expect(dialog(page).getByRole("button", { name: "Run it again" }).locator("kbd")).toHaveText("↵ Enter")
})

test("Escape cancels, and the focus goes back to where the window was opened", async ({ page }) => {
  await asking(page)
  await page.keyboard.press("Escape")
  await expect(dialog(page)).toBeHidden()
  await expect(page.getByRole("button", { name: "More actions" })).toBeFocused()
  expect((await (await page.request.get("/api/board")).json()).tickets.find((t: { id: string }) => t.id === DONE).column).toBe("done")
})

test("Enter confirms once, even pressed twice while the move is on its way", async ({ page }) => {
  // The move is answered here, and late: the ticket is shared with other tests,
  // and the second Enter has to land while the first is still waiting.
  let moves = 0
  await page.route("**/api/tickets/*/status", async (route) => {
    moves += 1
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({ json: { id: DONE, status: "Ready" } })
  })
  await asking(page)
  await page.keyboard.press("Enter")
  await page.keyboard.press("Enter")
  await expect(dialog(page)).toBeHidden()
  expect(moves).toBe(1)
})

test("the badges are hidden where the pointer is a finger", async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 800 } })
  const page = await context.newPage()
  await asking(page)
  await expect(dialog(page).locator("kbd").first()).toBeHidden()
  await context.close()
})
