import { expect, test, type Page } from "@playwright/test"

/* The way back to Ready, which starts a paid session, is never one click.
 *
 * On a Done card it waits behind "…", on the others behind a dialog that says
 * a session is paid for — and, on a Validated card, that the validation goes.
 * A Ready card is set aside, not "held": the toast says where it went, and
 * bringing it back asks first too.
 */

const page_of = (id: string) => `/?view=console/tickets/read/${id}`

async function open(page: Page, id: string, title: string) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(page_of(id))
  await expect(page.getByRole("heading", { name: title }).first()).toBeVisible()
}

const dialog = (page: Page) => page.getByRole("alertdialog")

test.use({ viewport: { width: 1440, height: 900 } })

test("a Done ticket runs again from its menu, and only once confirmed", async ({ page }) => {
  await open(page, "0000000000000000000000000000d0e0", "A finished ticket")
  await expect(page.getByRole("button", { name: /Make ready|Run again/ })).toHaveCount(0)
  await page.getByRole("button", { name: "More actions" }).click()
  await page.getByRole("menuitem", { name: "Run again" }).click()
  await expect(dialog(page)).toContainText("a session that is paid for")
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await expect(dialog(page)).toBeHidden()
  await page.reload()
  await expect(page.getByRole("button", { name: "More actions" })).toBeVisible()
})

test("making a Validated ticket ready says the validation goes", async ({ page }) => {
  await open(page, "0000000000000000000000000000fa11", "A validated ticket")
  await page.getByRole("button", { name: "Make ready" }).click()
  await expect(dialog(page)).toContainText("Its validation is withdrawn")
  await expect(dialog(page)).toContainText("a session that is paid for")
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await expect(dialog(page)).toBeHidden()
})

test("a Ready ticket is set aside in one click, and made ready again once confirmed", async ({ page }) => {
  await open(page, "0000000000000000000000000000a51d", "A ticket to set aside")
  const aside = page.getByRole("button", { name: "Set aside" })
  await expect(aside).toHaveAttribute("title", "The runner no longer touches it, until it is made ready again.")
  await aside.click()
  await expect(page.getByText("“A ticket to set aside” moved to Blocked")).toBeVisible()
  // The card sends the status it showed with the move back: until the board
  // has Notion's word for the first one it still says Ready, and the second
  // move reads as a ticket changed in Notion meanwhile. Let the first land and
  // read the board again.
  await expect
    .poll(async () => {
      const tickets = (await (await page.request.get("/api/board")).json()).tickets as {
        id: string
        status: string
        sync?: string
      }[]
      const ticket = tickets.find((item) => item.id === "0000000000000000000000000000a51d")
      return `${ticket?.status} ${ticket?.sync ?? ""}`.trim()
    })
    .toBe("Blocked")
  await page.reload()
  // Blocked, it opens on its discussion, and offers nothing else above it; set
  // aside by hand, nothing says why, and it runs again as it is in one click.
  await expect(page.getByRole("button", { name: "Make ready" })).toHaveCount(0)
  await expect(page.locator('[data-slot="ticket-talk-tab"]')).toHaveAttribute("aria-selected", "true")
  await expect(page.locator('[data-talk="question"]')).toContainText("Set aside by hand: no run said why.")
  await page.locator('[data-slot="quick-replies"]').getByRole("button", { name: "Run it again as it is" }).click()
  await expect(page.getByText("“A ticket to set aside” moved to Ready")).toBeVisible()
  // The window closes on the board, where every Ready card offers it: this one's.
  await expect(page.getByRole("group", { name: "A ticket to set aside" }).getByRole("button", { name: "Set aside" })).toBeVisible()
})

test("a ticket is given up from its menu, and lands in its own column", async ({ page }) => {
  await open(page, "0000000000000000000000000000c0de", "A ticket to give up")
  await page.getByRole("button", { name: "More actions" }).click()
  await page.getByRole("menuitem", { name: "Cancel the ticket" }).click()
  await expect(page.getByText("“A ticket to give up” moved to Cancelled")).toBeVisible()
  await expect
    .poll(async () => {
      const tickets = (await (await page.request.get("/api/board")).json()).tickets as {
        id: string
        column: string
        sync?: string
      }[]
      const ticket = tickets.find((item) => item.id === "0000000000000000000000000000c0de")
      return `${ticket?.column} ${ticket?.sync ?? ""}`.trim()
    })
    .toBe("cancelled")
})

test("a cancelled ticket wears its column, struck through, and is reopened as a draft", async ({ page }) => {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/?view=console/tickets")
  const column = page.locator("header").filter({ hasText: /^Cancelled/ })
  await expect(column.first()).toBeVisible()
  const title = page.getByRole("link", { name: "A ticket given up", exact: true }).first()
  await expect(title).toHaveCSS("text-decoration-line", "line-through")

  // Searchable by its status, like any other column.
  await page.getByRole("button", { name: /^Status/ }).click()
  await expect(page.getByRole("menuitemcheckbox", { name: /^Cancelled/ })).toBeVisible()
  await page.keyboard.press("Escape")

  await open(page, "0000000000000000000000000000c0ff", "A ticket given up")
  await expect(page.getByText("Cancelled", { exact: true }).first()).toBeVisible()
  await page.getByRole("button", { name: "Reopen" }).click()
  await expect(page.getByText("“A ticket given up” moved to Draft")).toBeVisible()
})
