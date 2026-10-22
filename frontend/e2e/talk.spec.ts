import { expect, test, type Page } from "@playwright/test"

/* A ticket's discussion, on its page.
 *
 * `e2e/console.py` writes one ticket blocked on a question a run asked. Its
 * card says it is waiting; its page opens on the discussion's tab, marked and
 * counted, with the question in it, signed by Ponos; and the answer is typed
 * in the console's own bar — without the bubble, which opens the workspace on
 * every page. Sending it is `decide.spec.ts`'s: an answer runs the ticket
 * again, and this one has to stay blocked for the other files that read it.
 */

const ASKING = "/?view=console/tickets/read/00000000000000000000000000000a5c"
const FIELD = "Answer Ponos or give it an instruction…"

async function open(page: Page, path: string) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

test.use({ viewport: { width: 1440, height: 900 } })

test("a ticket waiting on you is marked on the board by its Unblock button alone", async ({ page }) => {
  await open(page, "/")
  // Its own card, and not "the one card that waits": gestures.spec.ts sets a
  // Ready ticket aside, which is Blocked too for as long as that test runs.
  const id = ASKING.split("/").pop()
  const card = page.locator(`[data-ticket-card="${id}"]`)
  await expect(card).toHaveCount(1)
  await expect(card.locator('[data-slot="ticket-waiting"]')).toHaveCount(0)
  // The cause is in the button's tooltip, label first.
  await expect(card.locator(`[data-decide="${id}"]`)).toHaveAttribute("title", /^Question for you\n/)
})

test("a stopped card says why, and Unblock opens on the question's answer", async ({ page }) => {
  await open(page, "/")
  const id = ASKING.split("/").pop()
  // A blocked card keeps the cause's help in its Unblock button's tooltip only.
  const card = page.locator(`[data-ticket-card="${id}"]`)
  await expect(card).toHaveCount(1)
  const unblock = page.locator(`[data-decide="${id}"]`)
  await expect(unblock).toHaveText("Unblock")
  await expect(unblock).toHaveAttribute("title", /answer on the ticket and it carries on/)
  // The search offers the cause, and keeps the card by it.
  await page.getByRole("button", { name: "Cause" }).click()
  await page.getByRole("menuitemcheckbox", { name: /Question for you/ }).click()
  await page.keyboard.press("Escape")
  await expect(page).toHaveURL(/block=session\.question/)
  await expect(card).toHaveCount(1)
  // The window opens on its discussion: the question, and the field to answer it in.
  // The board is wider than the window once Done and Cancelled both hold a
  // card: the strip scrolls smoothly, so the button is brought in, and clicked
  // once it has stopped moving rather than mid-scroll. Brought to the middle:
  // scrolled just enough to show its edge, the strip snaps back to its first column.
  await unblock.evaluate((button) => button.scrollIntoView({ block: "center", inline: "center" }))
  await expect
    .poll(() =>
      unblock.evaluate(async (button) => {
        const before = button.getBoundingClientRect()
        await new Promise((done) => setTimeout(done, 150))
        const after = button.getBoundingClientRect()
        return after.left === before.left && after.top === before.top && after.right <= window.innerWidth
      })
    )
    .toBe(true)
  await unblock.click()
  await expect(page.locator('[data-slot="ticket-talk-tab"]')).toHaveAttribute("aria-selected", "true")
  await expect(page.locator('[data-talk="question"]')).toContainText("Which header, the dashboard's or the site's?")
  await expect(page.locator("[data-ticket-window]").getByRole("textbox", { name: FIELD })).toBeVisible()
})

test("its page opens on the discussion, marked, the question in it once, and the console's bar to answer", async ({ page }) => {
  await open(page, ASKING)
  const toggle = page.locator('[data-slot="ticket-talk-tab"]')
  await expect(toggle).toHaveAttribute("aria-selected", "true")
  await expect(toggle.locator('[data-slot="ticket-waiting-badge"]')).toBeVisible()
  await expect(toggle).toContainText("1")
  // Said once, signed by Ponos, with its face.
  const question = page.locator('[data-talk="question"]')
  await expect(page.getByRole("log").getByText("Which header, the dashboard's or the site's?")).toHaveCount(1)
  await expect(question.locator("[data-slot=message-header]")).toHaveText(/^\s*Ponos/)
  await expect(question.locator("[data-slot=turn-avatar] ponos-robot")).toBeVisible()
  // A free question has no reply to pick: running it again as it is, and the field.
  await expect(page.locator('[data-slot="quick-replies"] button')).toHaveText(["Run it again as it is"])
  const field = page.getByRole("textbox", { name: FIELD })
  await expect(page.locator('[data-slot="composer"]').filter({ has: field })).toBeVisible()

  // The bubble is the workspace's, here as anywhere.
  await expect(page.getByRole("button", { name: "Open the console" })).toBeVisible()
})
