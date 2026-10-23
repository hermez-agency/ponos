import { expect, test, type Page } from "@playwright/test"

/* The sessions: every conversation kept, found again and carried on.
 *
 * The conversation is `e2e/console.py`'s own `claude`. One console holds one
 * open session, so these tests take their turns one after another, on the
 * server the ideas page's tests have to themselves (`playwright.config.ts`).
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

test("a conversation is listed under Sessions, titled by its first message, and reopened", async ({ page }) => {
  await openConsole(page)
  await ask(page, "what is on the board?")
  await expect(page.getByText("Done. The board has 13 tickets.")).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("link", { name: "Sessions" }).first().click()
  const row = page.locator("[data-session]").filter({ hasText: "what is on the board?" })
  await expect(row).toBeVisible()
  await expect(row).toContainText("Default model")

  // Another conversation, so the first is no longer the open one.
  await page.getByRole("button", { name: "New session" }).click()
  await expect(page.getByRole("textbox", { name: FIELD })).toBeVisible()
  await expect(page.getByText("Done. The board has 13 tickets.")).toHaveCount(0)
  await page.keyboard.press("Escape")

  await row.getByRole("button", { name: /^More actions/ }).waitFor()
  await row.locator("button").first().click()
  await expect(page.getByText("Done. The board has 13 tickets.")).toBeVisible()
  await ask(page, "just the count, then")
  await expect(page.getByText("Resumed, and done. The board has 13 tickets.")).toBeVisible()
})

test("the model is chosen from the session, and only Claude's are offered without OpenRouter", async ({ page }) => {
  await openConsole(page)
  await page.locator("[data-model-picker]").click()
  const list = page.locator("[data-model-list]")
  await expect(list.getByText("Only the Claude models, until OpenRouter is configured.")).toBeVisible()
  await expect(list.getByRole("link", { name: "Set up OpenRouter" })).toBeVisible()
  for (const name of ["Opus", "Sonnet", "Haiku", "Fable"]) await expect(list.getByText(name, { exact: true })).toBeVisible()
  await list.getByText("Haiku", { exact: true }).click()
  await expect(page.locator("[data-model-picker]")).toHaveText(/Haiku/)
  expect((await (await page.request.get("/api/chat")).json()).model).toBe("haiku")
})

test("search looks in the titles and in what was said; delete asks for the box", async ({ page }) => {
  await openConsole(page)
  await page.keyboard.press("Escape")
  await page.getByRole("link", { name: "Sessions" }).first().click()

  const search = page.getByRole("searchbox")
  await search.fill("zzz-nothing")
  await expect(page.getByText("No session matches.")).toBeVisible()
  await search.fill("13 tickets")
  const row = page.locator("[data-session]").filter({ hasText: "what is on the board?" })
  await expect(row).toContainText("found in the conversation")

  await row.getByRole("button", { name: /^More actions/ }).click()
  await page.getByRole("menuitem", { name: "Rename" }).click()
  await page.locator("[data-session-title]").fill("The board count")
  await page.getByRole("button", { name: /^Save/ }).click()
  await search.fill("")
  const renamed = page.locator("[data-session]").filter({ hasText: "The board count" })
  await expect(renamed).toBeVisible()

  await renamed.getByRole("button", { name: /^More actions/ }).click()
  await page.getByRole("menuitem", { name: "Delete" }).click()
  const confirm = page.getByRole("button", { name: "Delete the session" })
  await expect(confirm).toBeDisabled()
  await page.locator("[data-confirm-delete]").click()
  await confirm.click()
  await expect(renamed).toHaveCount(0)
})

test("a new conversation starts from the drawer, on the same model, and the old one is in the history", async ({ page }) => {
  await openConsole(page)
  await page.locator("[data-new-chat]").click()
  await page.locator("[data-model-picker]").click()
  await page.locator("[data-model-list]").getByText("Haiku", { exact: true }).click()
  await ask(page, "first of two")
  await expect(page.getByText("Done. The board has 13 tickets.", { exact: true })).toBeVisible()

  await page.keyboard.press("Control+Shift+O")
  await expect(page.getByText("Done. The board has 13 tickets.", { exact: true })).toHaveCount(0)
  await expect(page.locator("[data-model-picker]")).toHaveText(/Haiku/)

  await page.locator("[data-talk-history]").click()
  await page.getByRole("menuitem", { name: /first of two/ }).click()
  await expect(page.getByText("Done. The board has 13 tickets.", { exact: true })).toBeVisible()

  await page.locator("[data-new-chat]").hover()
  await expect(page.getByRole("tooltip", { name: "Start a new conversation · Ctrl+Shift+O" })).toBeVisible()
})
