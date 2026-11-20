import { expect, test, type Page } from "@playwright/test"

/* A ticket's session tab, read from the local journal.
 *
 * `e2e/console.py` writes two runs of the blocked ticket: a short one that
 * failed, and a long one that asked a question. The tab opens on the newest,
 * from its end — the question it ended on — with the steps before it one
 * click away; the first run is a choice away, and reads as what it was: what
 * the agent said, its steps folded under it, the failed one marked.
 */

const ASKING = "/?view=console/tickets/read/00000000000000000000000000000a5c"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(ASKING)
  await page.getByRole("tab", { name: "Activity" }).click()
  await expect(page).toHaveURL(/[?&]tab=live$/)
}

test.use({ viewport: { width: 1440, height: 900 } })

test("the session tab reads the newest run from its end, and further back on request", async ({ page }) => {
  await open(page)
  const log = page.getByRole("log")
  await expect(log.getByText("Which header — the dashboard's, or the public site's?")).toBeVisible()
  await expect(page.getByText("250 steps")).toBeVisible()
  await expect(page.getByText("blocked · which header")).toBeVisible()
  // One page of the end, not the whole run: what came before the first thing
  // said on it is not the run's beginning.
  await expect(log.getByText("Starting again, from the start.")).not.toBeAttached()
  await expect(log.getByText("Before these lines")).toBeVisible()
  await page.getByRole("button", { name: "Earlier steps" }).click()
  await expect(log.getByText("Starting again, from the start.")).toBeAttached()
  await expect(log.getByText("Before these lines")).not.toBeAttached()
  // Two broad lines, and the 248 files read between them folded under the first.
  await expect(log.locator('[data-slot="session-line"]')).toHaveCount(2)
  await expect(log.getByText("part-12.py")).not.toBeAttached()
  await expect(log.locator('[data-slot="session-line-toggle"]')).toContainText("248 steps")
  await expect(page.getByRole("button", { name: "Earlier steps" })).not.toBeAttached()
})

test("an earlier run of the ticket is a choice away", async ({ page }) => {
  await open(page)
  await page.getByRole("combobox", { name: "Run" }).click()
  await page.getByRole("option", { name: /^#1 .* failed · claude\/sonnet · \$0\.12$/ }).click()
  await expect(page.getByText("an earlier session, read-only")).toBeVisible()
  await expect(page.getByText("3 steps")).toBeVisible()
  const log = page.getByRole("log")
  await expect(log.getByText("I read the brief first.")).toBeVisible()
  // Folded, and the step that failed still seen from outside.
  await expect(log.getByText("make test")).not.toBeAttached()
  const toggle = log.locator('[data-slot="session-line-toggle"]')
  await expect(toggle).toContainText("2 steps")
  await expect(toggle.locator('[data-slot="session-line-errors"]')).toContainText("1 step went wrong")
  await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
  await expect(log.getByText("make test")).toBeVisible()
  await expect(log.getByText("Error")).toBeVisible()
  await toggle.click()
  await expect(log.getByText("make test")).not.toBeAttached()

  // Everything at once, and folded again.
  await page.getByRole("button", { name: "Unfold everything" }).click()
  await expect(log.getByText("make test")).toBeVisible()
  await page.getByRole("button", { name: "Fold everything" }).click()
  await expect(log.getByText("make test")).not.toBeAttached()
})

test("a step of an earlier run starts the ticket again from there, with a message", async ({ page }) => {
  await open(page)
  await page.getByRole("combobox", { name: "Run" }).click()
  await page.getByRole("option", { name: /^#1 / }).click()
  const log = page.getByRole("log")
  await expect(log.getByText("I read the brief first.")).toBeVisible()
  // The newest run is the one the ticket goes on from; this one is not live,
  // so each of its steps offers a new session from it.
  await page.getByRole("button", { name: "Unfold everything" }).click()
  await expect(log.getByRole("button", { name: "Start again from here" })).toHaveCount(3)

  // Asked, not sent: the request is answered here, so the shared board keeps
  // its blocked ticket for the other cases.
  let sent: unknown = null
  await page.route(/\/api\/runs\/\d+\/fork$/, async (route) => {
    sent = route.request().postDataJSON()
    await route.fulfill({
      json: { ticket: "00000000000000000000000000000a5c", run: 1, position: 2, status: "Ready" },
    })
  })
  await log.getByText("make test").hover()
  await log.getByRole("button", { name: "Start again from here" }).nth(1).click()
  const dialog = page.getByRole("dialog", { name: "Start again from step 2" })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText(/The files are not taken back/)).toBeVisible()
  await dialog.getByRole("textbox", { name: "What the new session is told" }).fill("Use the Makefile's check target.")
  await dialog.getByRole("button", { name: "Start again" }).click()
  await expect(page.getByText("The ticket starts again from step 2")).toBeVisible()
  await expect(dialog).not.toBeAttached()
  expect(sent).toEqual({ position: 2, text: "Use the Makefile's check target." })
})
