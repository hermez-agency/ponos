import { expect, test, type Page } from "@playwright/test"

/* The conversation with the workspace: what Ponos says and does as it streams,
 * the turn kept that way, and Stop.
 *
 * The session is `e2e/console.py`'s own `claude`, which reads a file, runs a
 * command that fails and answers — or, asked to go slowly, starts a command
 * that would run for ten minutes. One conversation for the whole server, so the
 * tests here take their turns one after another — on a server of their own
 * (the "chat" project of `playwright.config.ts`), so that no other test opens a
 * console with one of these turns still running in it.
 */

test.describe.configure({ mode: "serial" })

const FIELD = "Ask the workspace, or type >status"

async function openConsole(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await page.getByRole("button", { name: "Open the console" }).click()
  await expect(page.getByRole("textbox", { name: FIELD })).toBeVisible()
}

async function ask(page: Page, text: string) {
  const field = page.getByRole("textbox", { name: FIELD })
  await field.fill(text)
  await field.press("Enter")
}

test("a turn streams what Ponos says and does, then the answer, and is kept that way", async ({ page }) => {
  await openConsole(page)
  await ask(page, "what is on the board?")

  // Ponos at work, and what it does as it does it: each tool a card, its state on it.
  await expect(page.locator("[data-slot=working] ponos-robot")).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible()
  const turn = page.locator("[data-slot=said][data-role=workspace]").last()
  await expect(turn.getByText("Let me look.")).toBeVisible()
  const read = turn.locator("[data-slot=chat-tool-call]").filter({ hasText: "Read" })
  await expect(read).toBeVisible()

  await expect(page.getByText("Done. The board has 13 tickets.")).toBeVisible()
  await expect(page.locator("[data-slot=working]")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0)
  // Signed by Ponos, with its face.
  await expect(turn).toContainText(/^\s*Ponos/)
  await expect(turn.locator("ponos-robot").first()).toBeVisible()
  // A tool that answered is done, one that failed says so — with what it answered.
  await expect(read).toHaveAttribute("data-status", "done")
  const check = turn.locator("[data-slot=chat-tool-call]").filter({ hasText: "python3 -m app.check" })
  await expect(check).toHaveAttribute("data-status", "error")
  await expect(turn.locator("[data-slot=chat-tool-result][data-state=error]")).toContainText("boom")
  await expect(turn.locator("[data-slot=said-footer]")).toContainText("$0.0123")

  // Read again from the server, the conversation is drawn as it was watched.
  await page.reload()
  await page.getByRole("button", { name: "Open the console" }).click()
  const kept = page.locator("[data-slot=said][data-role=workspace]").last()
  await expect(kept.getByText("Done. The board has 13 tickets.")).toBeVisible()
  await expect(kept.locator("[data-slot=chat-tool-call]")).toHaveCount(2)
  await expect(kept.locator("[data-slot=said-footer]")).toContainText("$0.0123")
  await expect(page.locator("[data-slot=said][data-role=you]").last()).toContainText("what is on the board?")
})

test("Stop ends the turn, says so, and the conversation carries on", async ({ page }) => {
  await openConsole(page)
  // The card no longer shows `claude --resume`: the session is read where the
  // drawer reads it, and has to be the same one once Stop has come and gone.
  const sessionOf = async () => (await (await page.request.get("/api/chat")).json()).session_id as string
  const session = await sessionOf()
  expect(session).toBeTruthy()

  await ask(page, "take it slowly")
  const sleeping = page.locator("[data-slot=chat-tool-call][data-status=running]").filter({ hasText: "sleep 600" })
  await expect(sleeping).toBeVisible({ timeout: 10_000 })
  const stop = page.getByRole("button", { name: "Stop" })
  await stop.click()
  // The double click: the second lands on a button already stopping, or gone.
  await stop.click({ timeout: 1_000 }).catch(() => {})

  await expect(page.getByText("stopped by you")).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0)
  await expect(page.getByRole("textbox", { name: FIELD })).toBeFocused()
  // The command it was in is not left running on the page.
  const stopped = page.locator("[data-slot=said][data-role=stopped]").last()
  await expect(stopped.locator("[data-slot=chat-tool-call]").filter({ hasText: "sleep 600" })).toHaveAttribute(
    "data-status",
    "error"
  )

  await ask(page, "just the count, then")
  await expect(page.getByText("Resumed, and done. The board has 13 tickets.")).toBeVisible()
  expect(await sessionOf()).toBe(session)
})

test("Escape from the empty field stops the turn, and leaves the drawer open", async ({ page }) => {
  await openConsole(page)
  const stopped = await page.getByText("stopped by you").count()
  await ask(page, "slowly, please")
  await expect(
    page.locator("[data-slot=chat-tool-call][data-status=running]").filter({ hasText: "sleep 600" })
  ).toBeVisible({ timeout: 10_000 })
  const field = page.getByRole("textbox", { name: FIELD })
  await field.focus()
  await field.press("Escape")
  await expect(page.getByText("stopped by you")).toHaveCount(stopped + 1)
  await expect(field).toBeVisible()
})

test("messages sent while Ponos answers wait, then are sent in order", async ({ page }) => {
  await openConsole(page)
  const field = page.getByRole("textbox", { name: FIELD })
  const answered = await page.getByText("Resumed, and done. The board has 13 tickets.").count()
  await ask(page, "hold-the-line")
  // Stop stays, and so does the arrow: the field is never locked.
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible()
  await expect(field).toBeEnabled()

  await ask(page, "first addition")
  await ask(page, "second addition")
  const waiting = page.locator("[data-slot=queued]")
  await expect(waiting).toHaveCount(2)
  await expect(waiting.first()).toContainText("first addition")
  await expect(waiting.last()).toContainText("second addition")
  await expect(waiting.first()).toContainText("waiting")
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible()

  // A waiting message can be changed, and taken back; the page knows it from the server.
  await waiting.last().getByRole("button", { name: "Edit the waiting message" }).click()
  const edit = waiting.last().getByRole("textbox", { name: "Edit the waiting message" })
  await edit.fill("second addition, reworded")
  await edit.press("Enter")
  await expect(waiting.last()).toContainText("second addition, reworded")
  await page.reload()
  await page.getByRole("button", { name: "Open the console" }).click()
  await expect(waiting).toHaveCount(2)
  await expect(waiting.last()).toContainText("second addition, reworded")

  // Both are sent once the turn is over, one after the other, and both answered.
  await expect(waiting).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByText("Resumed, and done. The board has 13 tickets.")).toHaveCount(answered + 2, {
    timeout: 30_000,
  })
  const mine = page.locator("[data-slot=said][data-role=you]")
  const texts = await mine.allInnerTexts()
  const sent = texts.filter((text) => /addition/.test(text))
  expect(sent[sent.length - 2]).toContain("first addition")
  expect(sent[sent.length - 1]).toContain("second addition, reworded")
})

test("Stop keeps the waiting messages: they are sent, or thrown away", async ({ page }) => {
  await openConsole(page)
  await ask(page, "take it slowly")
  await expect(
    page.locator("[data-slot=chat-tool-call][data-status=running]").filter({ hasText: "sleep 600" })
  ).toBeVisible({ timeout: 10_000 })
  await ask(page, "kept after the stop")
  const waiting = page.locator("[data-slot=queued]")
  await expect(waiting).toHaveCount(1)
  const stopped = await page.getByText("stopped by you").count()
  await page.getByRole("button", { name: "Stop" }).click()
  await expect(page.getByText("stopped by you")).toHaveCount(stopped + 1)

  // Nothing went on its own; the choice is offered, and another tab sees it too.
  const held = page.locator("[data-slot=queue-held]")
  await expect(held).toContainText("1 message is waiting")
  await expect(waiting).toHaveCount(1)
  const fresh = await (await page.request.get("/api/chat")).json()
  expect(fresh.held).toBe(true)
  expect(fresh.queue.map((item: { text: string }) => item.text)).toEqual(["kept after the stop"])

  await held.getByRole("button", { name: "Send" }).click()
  await expect(waiting).toHaveCount(0)
  await expect(page.getByText("Resumed, and done. The board has 13 tickets.").last()).toBeVisible()

  // And thrown away, the other way.
  await ask(page, "take it slowly again")
  await expect(
    page.locator("[data-slot=chat-tool-call][data-status=running]").filter({ hasText: "sleep 600" })
  ).toBeVisible({ timeout: 10_000 })
  await ask(page, "never sent")
  await expect(waiting).toHaveCount(1)
  await page.getByRole("button", { name: "Stop" }).click()
  await held.getByRole("button", { name: "Discard" }).click()
  // Asked first: what is thrown away cannot be brought back.
  const confirm = page.getByRole("alertdialog")
  await expect(confirm).toContainText("Throw the waiting message away?")
  await expect(waiting).toHaveCount(1)
  await confirm.getByRole("button", { name: /Discard/ }).click()
  await expect(page.getByText("Messages discarded")).toBeVisible()
  await expect(waiting).toHaveCount(0)
  await expect(held).toHaveCount(0)
  await expect(page.getByText("never sent")).toHaveCount(0)
})
