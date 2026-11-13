import { expect, test, type Page } from "@playwright/test"

/* The Context page: the standing context and the vault, as tabs.
 *
 * What is tested is the way a person goes: the page opens on the editor the
 * brief uses, already open, a save reaches the board, leaving with something typed asks first,
 * and the old address leads here rather than to the board.
 */

const LIST = "/?view=console/context/read/context"
const PROJECTS = "/?view=console/projects/list"
const LONG = Array.from({ length: 12 }, (_, line) => `Rule number ${line + 1} of the house.`).join("\n\n")

/** Write the context straight to the board, the way the console's own request does. */
const write = (page: Page, text: string) =>
  page.request.post("/api/context", { data: { text }, headers: { "X-Ponos": "1" } })

async function open(page: Page, path = LIST) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await write(page, LONG)
  await page.goto(path)
  if (path === LIST) await expect(page.getByRole("tab", { name: "Context", exact: true })).toBeVisible()
}

// One context for the whole board: the tests that write it do not run side by side.
test.describe.configure({ mode: "serial" })

const block = (page: Page) => page.locator('[data-slot="context-block"]')

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test("the context opens in the editor, is edited in place and saved", async ({ page }) => {
    await open(page)
    await expect(block(page).getByText("What every ticket is told, for all the projects.")).toBeVisible()
    await expect(block(page).locator(".ProseMirror")).toBeVisible()
    await expect(block(page).getByText("Rule number 1 of the house.")).toBeVisible()
    await expect(block(page).getByRole("button", { name: "See all" })).toHaveCount(0)
    await expect(block(page).getByRole("button", { name: "Edit" })).toHaveCount(0)
    // One title: the page's head, and the breadcrumb says it once.
    await expect(page.getByText("Global context")).toHaveCount(0)

    const save = block(page).getByRole("button", { name: "Save", exact: true })
    await expect(save).toBeDisabled()
    await block(page).locator(".ProseMirror").click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type(" Always in French.")
    await expect(block(page).getByText("Unsaved changes")).toBeVisible()

    // Leaving with something typed asks first, and staying keeps it.
    await page.getByRole("link", { name: "Schedules" }).click()
    await expect(page.getByRole("alertdialog")).toBeVisible()
    await page.getByRole("button", { name: "Keep editing" }).click()
    await expect(block(page).locator(".ProseMirror")).toBeVisible()

    await save.click()
    await expect(page.getByText("The context is saved")).toBeVisible()
    await expect(block(page).locator(".ProseMirror")).toBeVisible()

    // Written to the board, not just drawn.
    const saved = await (await page.request.get("/api/context")).json()
    expect(saved.text).toContain("Always in French.")
    await page.reload()
    await expect(block(page).getByText("Always in French.")).toBeVisible()
  })

  test("an empty context shows the empty editor", async ({ page }) => {
    await open(page)
    await write(page, "")
    await page.reload()
    await expect(block(page).locator(".ProseMirror")).toBeVisible()
    await expect(block(page).getByRole("button", { name: "Save", exact: true })).toBeDisabled()
  })

  test("five tabs, the address carries the tab, and the Projects page no longer holds the context", async ({ page }) => {
    await open(page)
    await expect(page.getByRole("tab")).toHaveCount(5)
    await expect(page.getByRole("tab", { name: "Context", exact: true })).toHaveAttribute("aria-selected", "true")
    await page.getByRole("tab", { name: "Vault" }).click()
    await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("console/context/read/context/vault")
    await expect(page.locator('[data-card="vault-key"]')).toBeVisible()
    await page.getByRole("tab", { name: "Context", exact: true }).click()
    await expect(block(page)).toBeVisible()

    // The menu has the page; the Projects page has no context block.
    await page.getByRole("link", { name: "Context", exact: true }).first().click()
    await expect(page.getByRole("tab")).toHaveCount(5)
    await page.goto(PROJECTS)
    await expect(page.getByText("Website").first()).toBeVisible()
    await expect(block(page)).toHaveCount(0)
  })

  test("the old addresses lead to the Context page", async ({ page }) => {
    await open(page)
    await page.goto("/?view=console/context/list")
    await expect(page).toHaveURL(/view=console\/context\/read\/context/)
    await expect(block(page)).toBeVisible()
    await page.goto("/?page=context")
    await expect(page).toHaveURL(/view=console\/context\/read\/context/)
  })

  test("a project's brief links to the Context page", async ({ page }) => {
    await open(page, "/?view=console/projects/read/0000000000000000000000000000cafe&tab=brief")
    await page.getByRole("link", { name: "Inherits the global context ↑" }).click()
    await expect(page).toHaveURL(/view=console\/context\/read\/context/)
    await expect(block(page)).toBeVisible()
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 780 } })

  test("the context fits a phone, with its tabs", async ({ page }) => {
    await open(page)
    await expect(block(page)).toBeVisible()
    await expect(page.getByRole("tab", { name: "Vault" })).toBeVisible()
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, "no sideways scroll").toBeLessThanOrEqual(390)
  })
})

test("the vault keeps a value it never shows again, and empties the form that carried it", async ({ page }) => {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  const value = "e2e_vault_value_0123456789"
  await page.goto("/?view=console/context/read/context/vault")
  await expect(page.locator('[data-card="vault-key"]')).toBeVisible()
  const form = page.locator('[data-card="vault-new"]')
  const field = form.locator('[data-slot="vault-value"]')
  await expect(field).toHaveAttribute("type", "password")
  await expect(field).toHaveAttribute("autocomplete", "off")
  await form.locator('[data-slot="vault-name"]').fill("E2E_DEPLOY_TOKEN")
  await field.fill(value)
  await form.locator('[data-slot="vault-projects"] [role="checkbox"]').first().click()
  // A console opened with its token alone: the token is what is typed again.
  const confirm = form.locator('[data-slot="vault-confirm"]')
  if (await confirm.count()) await confirm.fill("e2e")
  await form.locator('[data-slot="vault-create"]').click()
  const row = page.locator('[data-vault="E2E_DEPLOY_TOKEN"]')
  await expect(row).toBeVisible()
  await expect(row).toContainText("…6789")
  await expect(field).toHaveValue("")
  await expect(page.locator("body")).not.toContainText(value)
  // The key is a file here — no secret-tool, no PONOS_VAULT_KEY — and the page says where.
  await expect(page.locator('[data-slot="vault-key-file"]')).toBeVisible()
  await expect(page.locator('[data-slot="vault-key-where"]')).toContainText("vault.key")
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }))
  expect(stored).not.toContain(value)
})
