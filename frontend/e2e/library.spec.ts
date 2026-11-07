import { expect, test, type Page } from "@playwright/test"

/* The Context page's Library tab: reference files kept for the sessions.
 *
 * What is tested is the way a person goes: the two seeded files are listed
 * (`e2e/console.py`, `library_of`), filtered by project, by tag and by search,
 * previewed, renamed and moved to another scope, added by the picker or a drop,
 * deleted — and a file of a conversation is kept in one call. The files are
 * one library for the whole console: the tests that write it do not run side
 * by side.
 */

const LIBRARY = "/?view=console/context/read/context/library"
const WRITE = { "X-Ponos": "1" }

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIBRARY)
  await expect(page.locator('[data-slot="library-page"]')).toBeVisible()
}

const rows = (page: Page) => page.locator('[data-slot="library-row"], [data-slot="library-card"]')

test.describe.configure({ mode: "serial" })
test.use({ viewport: { width: 1440, height: 900 } })

test("the tab sits beside the others and lists the files with the room they take", async ({ page }) => {
  await open(page)
  await expect(page.getByRole("tab", { name: "Library", exact: true })).toBeVisible()
  await expect(rows(page)).toHaveCount(2)
  await expect(page.getByText("The brand charter")).toBeVisible()
  await expect(page.locator('[data-slot="library-total"]')).toContainText("2 file(s)")
})

test("the list is filtered by project, by tag and by search", async ({ page }) => {
  await open(page)
  // Newsletter is in scope of the logo (every project) and not of the charter.
  await page.getByLabel("Filter by project").selectOption({ label: "Newsletter" })
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText("logo.png")
  await page.getByLabel("Filter by project").selectOption("")
  await page.getByLabel("Filter by tag").selectOption("client")
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText("charter.pdf")
  await page.getByLabel("Filter by tag").selectOption("")
  await page.getByLabel("Search the library").fill("white")
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText("logo.png")
})

test("an image and a PDF open in a preview, and the thumbnails view draws cards", async ({ page }) => {
  await open(page)
  await rows(page).filter({ hasText: "logo.png" }).getByRole("button", { name: "Preview" }).click()
  await expect(page.locator("img[data-slot='library-preview']")).toBeVisible()
  await page.getByRole("button", { name: "Close" }).click()
  await rows(page).filter({ hasText: "charter.pdf" }).getByRole("button", { name: "Preview" }).click()
  await expect(page.locator("iframe[data-slot='library-preview']")).toBeVisible()
  await page.getByRole("button", { name: "Close" }).click()

  await page.getByRole("button", { name: "Thumbnails" }).click()
  await expect(page.locator('[data-slot="library-card"]')).toHaveCount(2)
  await page.getByRole("button", { name: "List" }).click()
  await expect(page.locator('[data-slot="library-row"]')).toHaveCount(2)
})

test("a file is served under its own type, in a sandbox, and downloaded on request", async ({ page }) => {
  await open(page)
  const list = await (await page.request.get("/api/library")).json()
  const logo = list.files.find((file: { name: string }) => file.name === "logo.png")
  const shown = await page.request.get(`/api/library/${logo.id}/file`)
  expect(shown.headers()["content-type"]).toContain("image/png")
  expect(shown.headers()["content-security-policy"]).toContain("sandbox")
  const saved = await page.request.get(`/api/library/${logo.id}/file?download=1`)
  expect(saved.headers()["content-disposition"]).toContain("attachment")
})

test("a file is renamed and moved to another scope", async ({ page }) => {
  await open(page)
  await rows(page).filter({ hasText: "logo.png" }).getByRole("button", { name: "Edit" }).click()
  const editor = page.locator('[data-slot="library-editor"]')
  await editor.getByLabel("Name").fill("logo-white.png")
  await editor.getByLabel("Tags").fill("brand, logo")
  await editor.getByLabel("Newsletter").check()
  await editor.getByRole("button", { name: "Save" }).click()
  const moved = rows(page).filter({ hasText: "logo-white.png" })
  await expect(moved).toContainText("Newsletter")
  await expect(moved).toContainText("logo")

  // Website is no longer in its scope.
  await page.getByLabel("Filter by project").selectOption({ label: "Website" })
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText("charter.pdf")
})

test("a file is added with the picker, then deleted", async ({ page }) => {
  await open(page)
  await page.locator('[data-slot="library-input"]').setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("What the client asked for."),
  })
  await expect(rows(page).filter({ hasText: "notes.txt" })).toHaveCount(1)
  await rows(page).filter({ hasText: "notes.txt" }).getByRole("button", { name: "Delete" }).click()
  await expect(rows(page).filter({ hasText: "notes.txt" })).toHaveCount(0)
})

test("a file dropped on the tab is kept, then deleted", async ({ page }) => {
  await open(page)
  const carried = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(["The client's brief."], "dropped.md", { type: "text/markdown" }))
    return transfer
  })
  const target = page.locator('[data-slot="library-drop"]')
  await target.dispatchEvent("dragover", { dataTransfer: carried })
  await expect(target).toHaveAttribute("data-over", "true")
  await target.dispatchEvent("drop", { dataTransfer: carried })
  await expect(rows(page).filter({ hasText: "dropped.md" })).toHaveCount(1)
  await rows(page).filter({ hasText: "dropped.md" }).getByRole("button", { name: "Delete" }).click()
  await expect(rows(page).filter({ hasText: "dropped.md" })).toHaveCount(0)
})

test("a file of a conversation is kept in the library in one call", async ({ page }) => {
  await open(page)
  const chat = "0123456789ab"
  const up = await page.request.post(`/api/chat/${chat}/attachments?name=brief.pdf`, {
    headers: { ...WRITE, "Content-Type": "application/pdf" },
    data: Buffer.from("%PDF-1.4 brief"),
  })
  expect(up.ok()).toBe(true)
  const attached = await up.json()
  const kept = await page.request.post(`/api/chat/${chat}/attachments/${attached.id}/keep`, { headers: WRITE })
  expect(kept.ok()).toBe(true)
  expect((await kept.json()).kept.name).toBe("brief.pdf")
  await page.reload()
  await expect(rows(page).filter({ hasText: "brief.pdf" })).toHaveCount(1)
  await rows(page).filter({ hasText: "brief.pdf" }).getByRole("button", { name: "Delete" }).click()
  await expect(rows(page).filter({ hasText: "brief.pdf" })).toHaveCount(0)
})
