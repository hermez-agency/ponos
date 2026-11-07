import { expect, test, type Page, type Route } from "@playwright/test"

/* A write is drawn before the server has answered it, and drawn back when the
 * server refuses.
 *
 * Every write here is caught on its way out and held until the test lets it
 * go, so the page is looked at while the server is still "thinking" — which is
 * all of a second or two on a busy machine. Nothing reaches the board the other
 * files read: the answers are the test's.
 */

const FIELD = "Answer Ponos or give it an instruction…"

async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

/** A route held until `release`, then answered with `answer` — a status and a body. */
function held(page: Page, url: string, method = "POST") {
  let release!: (answer: { status: number; json: unknown }) => void
  const gate = new Promise<{ status: number; json: unknown }>((resolve) => (release = resolve))
  let reached = 0
  void page.route(url, async (route: Route) => {
    if (route.request().method() !== method) return route.fallback()
    reached += 1
    await route.fulfill(await gate)
  })
  return { release, reached: () => reached }
}

test.use({ viewport: { width: 1440, height: 900 } })

async function newTicket(page: Page, title: string) {
  await page.getByRole("link", { name: /New ticket|Nouveau ticket/ }).first().click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("Title").fill(title)
  await dialog.getByLabel("Title").press("Control+Enter")
  return dialog
}

test("a new ticket closes its form and is drawn before the server answers", async ({ page }) => {
  const write = held(page, "**/api/tickets")
  await open(page)
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
  const dialog = await newTicket(page, "Drawn at once")
  await expect(dialog).toBeHidden()
  await expect(page.getByText("Drawn at once").filter({ visible: true }).first()).toBeVisible()
  expect(write.reached()).toBe(1)
  write.release({ status: 200, json: { id: "0000000000000000000000000000f00d", title: "Drawn at once" } })
  await expect(page.getByText("Drawn at once").filter({ visible: true })).toHaveCount(1)
})

test("a new ticket the server refuses is taken off again, and the reason is said", async ({ page }) => {
  const write = held(page, "**/api/tickets")
  await open(page)
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
  const dialog = await newTicket(page, "Refused one")
  await expect(dialog).toBeHidden()
  await expect(page.getByText("Refused one").filter({ visible: true }).first()).toBeVisible()
  write.release({ status: 500, json: { error: "The board said no" } })
  await expect(page.getByText("The ticket could not be created")).toBeVisible()
  await expect(page.getByText("The board said no")).toBeVisible()
  await expect(page.getByText("Refused one").filter({ visible: true })).toHaveCount(0)
})

test("a status change is said and drawn before the server answers, and put back when refused", async ({ page }) => {
  const write = held(page, "**/api/tickets/*/status")
  await open(page)
  const card = page.getByRole("group", { name: "A long ticket" })
  await card.getByRole("button", { name: "Set aside" }).click()
  await expect(page.getByText("“A long ticket” moved to Blocked")).toBeVisible()
  await expect(card.getByRole("button", { name: "Set aside" })).toHaveCount(0)
  write.release({ status: 500, json: { error: "The board said no" } })
  await expect(page.getByText("could not move “A long ticket”")).toBeVisible()
  await expect(card.getByRole("button", { name: "Set aside" })).toBeVisible()
})

test("a message to a ticket is drawn before the server answers, and taken off when refused", async ({ page }) => {
  const write = held(page, "**/api/tickets/*/talk")
  await open(page, "/?view=console/tickets/read/000000000000000000000000000abcde")
  await page.locator('[data-slot="ticket-talk-tab"]').click()
  const field = page.getByRole("textbox", { name: FIELD })
  await field.fill("Optimistic words")
  await field.press("Enter")
  await expect(page.getByText("Optimistic words")).toBeVisible()
  await expect(field).toHaveValue("")
  write.release({ status: 500, json: { error: "The board said no" } })
  await expect(page.getByText("not written")).toBeVisible()
  await expect(page.getByText("Optimistic words")).toHaveCount(0)
})
