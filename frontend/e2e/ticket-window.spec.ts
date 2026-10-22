import { expect, test, type Page } from "@playwright/test"

/* A click on a ticket opens it in a window over the board.
 *
 * It used to leave the board for the ticket's page, and the way back put you at
 * the top of it. What is tested is the way a user goes: a click on a card or a
 * row of the table, the window over the list, then either of its two buttons —
 * the page, at the address it always had, or the cross and Escape, back to the
 * board where it was. The window is in the address, under the board: a reload
 * opens it again there, and Back closes it.
 */

const LONG = "000000000000000000000000000abcde"
const BOARD = "/?view=console/tickets/list/board"

async function open(page: Page, path = BOARD) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  await expect(page.getByRole("link", { name: "A long ticket" })).toBeVisible()
}

const window_ = (page: Page) => page.getByRole("dialog")

async function openLong(page: Page) {
  await page.getByRole("link", { name: "A long ticket" }).click()
  await expect(window_(page)).toBeVisible()
  await expect(window_(page).locator('[data-slot="dialog-title"]')).toHaveText("A long ticket")
  await expect(window_(page).getByText("#000abcde")).toBeVisible()
  // The ticket's page, drawn inside: its facts and, once read, its brief.
  await expect(window_(page).getByText("no project — a document")).toBeVisible()
  await expect(window_(page).getByText("Part 40")).toBeAttached()
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("a card opens its ticket in a window, and the full page from there", async ({ page }) => {
    await open(page)
    await openLong(page)
    // The board is still there, under it: the address names it, then the ticket.
    expect(new URL(page.url()).searchParams.get("view")).toBe(`console/tickets/list/board/tickets/read/${LONG}`)
    await page.reload()
    await expect(window_(page).locator('[data-slot="dialog-title"]')).toHaveText("A long ticket")
    await expect(page.locator(`[data-ticket-card="${LONG}"]`)).toBeAttached()

    await window_(page).getByRole("link", { name: "Open the full page" }).click()
    await expect(page).toHaveURL(new RegExp(`tickets/read/${LONG}`))
    await expect(window_(page)).not.toBeAttached()
    await expect(page.locator('[data-slot="admin-header"] h2')).toHaveText("A long ticket")
  })

  test("the cross and Escape close the window, back on the board where it was", async ({ page }) => {
    await open(page)
    await openLong(page)
    await window_(page).getByRole("button", { name: "Close" }).click()
    await expect(window_(page)).not.toBeAttached()
    await expect(page).toHaveURL(/tickets\/list\/board/)

    await openLong(page)
    await page.keyboard.press("Escape")
    await expect(window_(page)).not.toBeAttached()
    await expect(page.getByRole("link", { name: "A long ticket" })).toBeVisible()

    await openLong(page)
    await page.goBack()
    await expect(window_(page)).not.toBeAttached()
    expect(new URL(page.url()).searchParams.get("view")).toBe("console/tickets/list/board")
  })

  test("changing tab moves neither the header nor the tabs", async ({ page }) => {
    await open(page)
    await openLong(page)
    const title = window_(page).locator('[data-slot="dialog-title"]')
    const tab = window_(page).locator('[data-slot="ticket-talk-tab"]')
    const before = [(await title.boundingBox())?.y, (await tab.boundingBox())?.y]
    await tab.click()
    await expect(tab).toHaveAttribute("data-state", "active")
    await window_(page).locator('[data-slot="ticket-brief-tab"]').click()
    await window_(page).locator('[data-slot="ticket-live-tab"]').click()
    await expect(window_(page).locator('[data-slot="ticket-live-tab"]')).toHaveAttribute("data-state", "active")
    expect([(await title.boundingBox())?.y, (await tab.boundingBox())?.y]).toEqual(before)
  })

  test("the table opens the same window from a ticket's title", async ({ page }) => {
    await open(page, "/?view=console/tickets/list/table")
    await openLong(page)
    await page.keyboard.press("Escape")
    await expect(window_(page)).not.toBeAttached()
    await expect(page).toHaveURL(/tickets\/list\/table/)
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("the window takes the whole screen", async ({ page }) => {
    await open(page)
    await openLong(page)
    await expect
      .poll(async () => {
        const box = await window_(page).boundingBox()
        return box && [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)]
      })
      .toEqual([0, 0, 390, 844])
  })
})
