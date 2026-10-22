import { expect, test, type Page } from "@playwright/test"

/* The conversation with the workspace: Ponos while it works, the steps folded,
 * and Stop.
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

test("a turn shows Ponos at work, then the answer, with its steps as a timeline", async ({ page }) => {
  await openConsole(page)
  await ask(page, "what is on the board?")

  const thinking = page.locator("[data-slot=thinking]:not([data-done])")
  await expect(thinking.locator("ponos-robot")).toBeVisible()
  // The steps are there as they come, in plain words — never the command.
  await expect(thinking.getByText("I read the project’s code").first()).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible()
  await expect(page.getByText("python3 -m app.check")).toBeHidden()
  await expect(page.getByRole("button", { name: /Show the steps|Hide the steps/ })).toHaveCount(0)

  await expect(page.getByText("Done. The board has 13 tickets.")).toBeVisible()
  await expect(thinking).toHaveCount(0)
  // Signed by Ponos, with its face — not by "the workspace".
  const answer = page.locator("[data-slot=message]").filter({ hasText: "Done. The board has 13 tickets." })
  await expect(answer.locator("[data-slot=message-header]")).toHaveText(/^\s*Ponos/)
  await expect(answer.locator("[data-slot=turn-avatar] ponos-robot")).toBeVisible()
  const summary = page.locator("[data-slot=steps]").last()
  await expect(summary).toContainText("3 steps")
  await expect(summary).toContainText("$0.0123")
  // One card per step, closed; the one that failed says so, with its mark.
  const read = page.getByRole("button", { name: /I read the project’s code/ }).last()
  const failed = page.getByRole("button", { name: /failed.*I work on the project/ }).last()
  await expect(read).toHaveAttribute("aria-expanded", "false")
  await expect(failed).toHaveAttribute("aria-expanded", "false")
  await expect(page.getByText("python3 -m app.check")).toBeHidden()

  // The technical detail is one click down.
  await failed.click()
  await expect(failed).toHaveAttribute("aria-expanded", "true")
  await expect(page.getByText("python3 -m app.check")).toBeVisible()
  await failed.press("Enter")
  await expect(failed).toHaveAttribute("aria-expanded", "false")

  await summary.getByRole("button", { name: "Expand all" }).click()
  await expect(read).toHaveAttribute("aria-expanded", "true")
  await summary.getByRole("button", { name: "Collapse all" }).click()
  await expect(read).toHaveAttribute("aria-expanded", "false")
})

test("Stop ends the turn, says so, and the conversation carries on", async ({ page }) => {
  await openConsole(page)
  // The card no longer shows `claude --resume`: the session is read where the
  // drawer reads it, and has to be the same one once Stop has come and gone.
  const sessionOf = async () => (await (await page.request.get("/api/chat")).json()).session_id as string
  const session = await sessionOf()
  expect(session).toBeTruthy()

  await ask(page, "take it slowly")
  await expect(page.getByText("fixing an error…")).toBeVisible({ timeout: 10_000 })
  await expect(page.locator("[data-slot=step][data-state=running]")).toBeVisible()
  const stop = page.getByRole("button", { name: "Stop" })
  await stop.click()
  // The double click: the second lands on a button already stopping, or gone.
  await stop.click({ timeout: 1_000 }).catch(() => {})

  await expect(page.getByText("stopped by you")).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0)
  await expect(page.getByRole("textbox", { name: FIELD })).toBeFocused()
  await expect(page.locator("[data-slot=steps]").last()).toContainText("4 steps")

  await ask(page, "just the count, then")
  await expect(page.getByText("Resumed, and done. The board has 13 tickets.")).toBeVisible()
  expect(await sessionOf()).toBe(session)
})

test("Escape from the empty field stops the turn, and leaves the drawer open", async ({ page }) => {
  await openConsole(page)
  const stopped = await page.getByText("stopped by you").count()
  await ask(page, "slowly, please")
  await expect(page.getByText("fixing an error…")).toBeVisible({ timeout: 10_000 })
  await expect(page.locator("[data-slot=step][data-state=running]")).toBeVisible()
  const field = page.getByRole("textbox", { name: FIELD })
  await field.focus()
  await field.press("Escape")
  await expect(page.getByText("stopped by you")).toHaveCount(stopped + 1)
  await expect(field).toBeVisible()
})
