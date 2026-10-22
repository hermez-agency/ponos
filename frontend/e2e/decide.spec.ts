import { expect, test, type Page } from "@playwright/test"

/* A blocked ticket's discussion, and the Decide tab, from its card and on itself.
 *
 * `e2e/console.py` writes tickets blocked on a report that names its kind of
 * stop — missing access, with two options; one whose session proposes to close
 * it as a duplicate — and one in review whose report says what to check. A
 * blocked card offers Unblock, which opens the ticket's window — one window,
 * nothing beside it — on its discussion: the question said once, in Ponos's
 * bubble, and under it the quick replies, each a click that answers and runs
 * it again. A card in review offers Decide, a tab of its own; a choice there
 * that needs words opens its field, and sending it moves the ticket and leaves
 * the instruction on it, where the next session reads it.
 */

const READ = "00000000000000000000000000b10c01"
const ACT = "00000000000000000000000000b10c02"
const CLOSE = "00000000000000000000000000b10c03"
const GIVE_UP = "00000000000000000000000000b10c04"
const PLAIN = "00000000000000000000000000b10c05"
const TYPED = "00000000000000000000000000b10c06"
const REVIEW = "00000000000000000000000000de1c01"
const LONG = "000000000000000000000000000abcde"

async function open(page: Page, path = "/") {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const ticketWindow = (page: Page) => page.locator("[data-ticket-window]")
const tab = (page: Page) => page.locator('[data-slot="ticket-decide-tab"]')
const talkTab = (page: Page) => page.locator('[data-slot="ticket-talk-tab"]')
const panel = (page: Page) => page.locator('[data-slot="ticket-decision"]')
const question = (page: Page) => page.locator('[data-talk="question"]')
const replies = (page: Page) => page.locator('[data-slot="quick-replies"] button')

/** The card's button, clicked: the window opens, and nothing else opens. */
async function unblock(page: Page, id: string) {
  const button = page.locator(`[data-decide="${id}"]`)
  await button.scrollIntoViewIfNeeded()
  await button.click()
  await expect(ticketWindow(page)).toBeVisible()
  await expect(page.getByRole("dialog")).toHaveCount(1)
}

/** The same, on a blocked card: the window is on the discussion, and the question in it. */
async function answer(page: Page, id: string) {
  await unblock(page, id)
  await expect(talkTab(page)).toHaveAttribute("aria-selected", "true")
  await expect(question(page)).toBeVisible()
}

test.describe("on a desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("a blocked card offers Unblock and nothing else", async ({ page }) => {
    await open(page)
    const button = page.locator(`[data-decide="${READ}"]`)
    await expect(button).toHaveText("Unblock")
    const card = page.locator("div.rounded-2xl.p-3", { has: button }).last()
    await expect(card.getByRole("button")).toHaveText(["Unblock"])
    await expect(card.locator('[data-slot="block-action"]')).toHaveCount(0)
    // The cause is no badge of its own any more: the button is the only mark.
    await expect(card.locator('[data-slot="ticket-waiting"]')).toHaveCount(0)
  })

  test("Unblock opens one window on the discussion: the question once, and its quick replies", async ({ page }) => {
    await open(page)
    await answer(page, READ)
    // No tab of its own: the discussion wears the mark of a question waiting.
    await expect(tab(page)).toHaveCount(0)
    await expect(talkTab(page).locator('[data-slot="ticket-waiting-badge"]')).toBeVisible()
    // What is done, why it stops, then the question — said once, nowhere else.
    await expect(question(page)).toContainText("ticket/tailscale")
    await expect(question(page)).toContainText("I have no SSH access to the server")
    await expect(question(page).locator('[data-slot="talk-ask"]')).toHaveText("Which way do you prefer?")
    await expect(ticketWindow(page).getByText("Which way do you prefer?")).toHaveCount(1)
    // Already on the discussion: the button above it would only point at where you are.
    await expect(ticketWindow(page).locator(`[data-decide="${READ}"]`)).toHaveCount(0)
    // One reply per option, in its own words, and running it again as it is.
    await expect(replies(page)).toHaveText([
      "Give me an SSH key",
      "Install it yourself and tell me",
      "Run it again as it is",
    ])
    // One field, the composer's, and the rarer gestures behind ⋯.
    await expect(ticketWindow(page).getByRole("textbox")).toHaveCount(1)
    await expect(ticketWindow(page).getByRole("textbox", { name: "Answer Ponos or give it an instruction…" })).toBeVisible()
    await ticketWindow(page).locator('[data-slot="talk-menu"]').click()
    await expect(page.getByRole("menuitem")).toHaveText(["Run it again as it is", "Abandon", "See the session"])
    await page.keyboard.press("Escape")
    // The other tabs are a click away, and the button in the window's header comes back to it.
    await ticketWindow(page).locator('[data-slot="ticket-brief-tab"]').click()
    await expect(question(page)).toBeHidden()
    await ticketWindow(page).locator(`[data-decide="${READ}"]`).click()
    await expect(talkTab(page)).toHaveAttribute("aria-selected", "true")
    await expect(question(page)).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(ticketWindow(page)).toBeHidden()
  })

  test("a ticket that waits on nobody has no Decide tab, and an old Unblock address opens the discussion", async ({ page }) => {
    await open(page)
    await page.getByRole("link", { name: "A long ticket" }).click()
    await expect(ticketWindow(page).locator('[data-slot="ticket-brief-tab"]')).toBeVisible()
    await expect(tab(page)).toHaveCount(0)
    await open(page, `/?view=console/tickets/read/${LONG}&tab=unblock`)
    await expect(page.locator('[data-slot="ticket-brief-tab"]')).toBeVisible()
    await expect(tab(page)).toHaveCount(0)
    await expect(talkTab(page)).toHaveAttribute("aria-selected", "true")
  })

  test("on its page, the tab is in the address, and Unblock switches to the discussion", async ({ page }) => {
    await open(page, `/?view=console/tickets/read/${READ}&tab=unblock`)
    await expect(talkTab(page)).toHaveAttribute("aria-selected", "true")
    await expect(question(page)).toContainText("Which way do you prefer?")
    await page.locator('[data-slot="ticket-brief-tab"]').click()
    await expect(page).toHaveURL(/[?&]tab=brief$/)
    await page.locator(`[data-decide="${READ}"]`).click()
    await expect(talkTab(page)).toHaveAttribute("aria-selected", "true")
    await expect(page).toHaveURL(/[?&]tab=discussion$/)
  })

  test("a quick reply answers and runs it again, and the window closes on the board", async ({ page }) => {
    await open(page)
    await answer(page, ACT)
    await replies(page).filter({ hasText: "Install it yourself and tell me" }).click()
    await expect(page.getByText("“Choose the host” moved to Ready")).toBeVisible()
    // Unblocked: the window has nothing more to say, and the card is back on the board.
    await expect(ticketWindow(page)).toBeHidden()
    const said = (await (await page.request.get(`/api/tickets/${ACT}/talk`)).json()) as {
      messages: { text: string }[]
    }
    expect(said.messages[said.messages.length - 1].text).toContain("Decision: option 2, “Install it yourself and tell me”.")
  })

  test("a sentence typed under the question is its answer, and runs it again", async ({ page }) => {
    await open(page)
    await answer(page, TYPED)
    const field = ticketWindow(page).getByRole("textbox", { name: "Answer Ponos or give it an instruction…" })
    await field.fill("Use the key in 1Password.")
    await field.press("Control+Enter")
    await expect(page.getByText("“Pick the header” moved to Ready")).toBeVisible()
    await expect(ticketWindow(page)).toBeHidden()
    const said = (await (await page.request.get(`/api/tickets/${TYPED}/talk`)).json()) as {
      messages: { text: string }[]
    }
    const last = said.messages[said.messages.length - 1].text
    expect(last).toContain("Decision: an instruction.")
    expect(last).toContain("Use the key in 1Password.")
  })

  test("a proposal to close the ticket is accepted in one click, and files it as done", async ({ page }) => {
    await open(page)
    await answer(page, CLOSE)
    await expect(replies(page)).toHaveText(["Yes, close it", "No", "Run it again as it is"])
    await replies(page).filter({ hasText: "Yes, close it" }).click()
    await expect(page.getByText("“Close the duplicate” moved to Done")).toBeVisible()
    // Nothing to run: Ponos is not shown at work on it.
    await expect(ticketWindow(page).locator('[data-talk="working"]')).toHaveCount(0)
    const said = (await (await page.request.get(`/api/tickets/${CLOSE}/talk`)).json()) as {
      messages: { text: string }[]
    }
    expect(said.messages[said.messages.length - 1].text).toContain("Decision: yes, close it — moved to done.")
  })

  test("abandon is behind ⋯, asks first, and files the ticket as cancelled", async ({ page }) => {
    await open(page)
    await answer(page, GIVE_UP)
    await ticketWindow(page).locator('[data-slot="talk-menu"]').click()
    await page.getByRole("menuitem", { name: "Abandon" }).click()
    const asking = page.getByRole("alertdialog")
    await expect(asking).toContainText("Abandon — move to cancelled")
    await asking.getByRole("button", { name: /^Abandon/ }).click()
    await expect(page.getByText("“Move the old backups” moved to Cancelled")).toBeVisible()
  })

  test("run it again as it is puts it back in Ready", async ({ page }) => {
    await open(page)
    await answer(page, PLAIN)
    await replies(page).filter({ hasText: "Run it again as it is" }).click()
    await expect(page.getByText("“Renew the certificate” moved to Ready")).toBeVisible()
  })

  test("a card in review says what it delivered, what to check, and how to decide", async ({ page }) => {
    await open(page)
    await unblock(page, REVIEW)
    await expect(tab(page)).toHaveAttribute("aria-selected", "true")
    await expect(tab(page)).toHaveText("Decide")
    await expect(panel(page)).toContainText("Adds a share button under each article.")
    await expect(panel(page).getByRole("link", { name: /Pull request/ })).toHaveAttribute(
      "href",
      "https://github.com/example/website/pull/12"
    )
    await expect(panel(page).locator('[data-slot="decision-caveats"] li')).toHaveText([
      "not tried on Safari",
      "the screenshots on mobile are missing",
    ])
    for (const name of ["Validate", "Send back with an instruction", "Take the screenshots", "Reject"])
      await expect(panel(page).getByRole("button", { name, exact: true })).toBeVisible()
    // A ready-made instruction opens written out, for you to send or to change.
    await panel(page).getByRole("button", { name: "Take the screenshots", exact: true }).click()
    await expect(panel(page).getByRole("textbox")).toHaveValue(/Take the screenshots that were asked for/)
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test("Unblock opens the ticket's window on its discussion, the replies read in full", async ({ page }) => {
    await open(page)
    // Brought to the middle of the screen first: left at its edge, the button
    // sits under the bottom bar, or on a card not yet drawn (content-visibility).
    const unblock = page.locator(`[data-decide="${READ}"]`)
    await unblock.evaluate((button) => button.scrollIntoView({ block: "center" }))
    await unblock.tap()
    await expect(page.getByRole("dialog")).toHaveCount(1)
    await expect(talkTab(page)).toHaveAttribute("aria-selected", "true")
    await expect(question(page)).toContainText("Which way do you prefer?")
    // Once the window has grown in: it opens from slightly smaller. Each reply
    // is a thumb high, inside the screen, and none of its words cut.
    const reply = replies(page).first()
    await expect.poll(async () => (await reply.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(32)
    for (const one of await replies(page).all()) {
      const box = await one.boundingBox()
      expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390)
      expect(await one.evaluate((button) => button.scrollWidth <= button.clientWidth)).toBe(true)
    }
  })
})
