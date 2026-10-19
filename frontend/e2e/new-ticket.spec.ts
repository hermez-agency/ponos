import { expect, test, type Page } from "@playwright/test"

/* A new ticket says how urgent it is, which road it takes and on which model,
 * from the dialog — two columns, the brief on the left and the settings on the
 * right — and is either launched or kept as a draft.
 *
 * The three used to be set in Notion afterwards, by hand. The board here is
 * Markdown, which has every column: all three are offered. What is sent is
 * caught on its way out rather than written, so the board the other tests read
 * keeps the tickets it was made with.
 */

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
  await page.getByRole("link", { name: /New ticket|Nouveau ticket/ }).first().click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toBeVisible()
  return dialog
}

/* The model is the package's select, a combobox of its own, not a <select>:
 * opened, then an option picked from the list it draws. Found by the label its
 * group opens with. */
const choiceField = (dialog: ReturnType<Page["getByRole"]>, field: string) =>
  dialog
    .getByRole("group")
    .filter({ hasText: new RegExp(`^${field}`) })
    .getByRole("combobox")

async function choose(page: Page, dialog: ReturnType<Page["getByRole"]>, field: string, option: string) {
  await choiceField(dialog, field).click()
  await page.getByRole("option", { name: option, exact: true }).click()
}

/* The type is all in view, a button each; so is a code ticket's sub-type. */
const segment = (dialog: ReturnType<Page["getByRole"]>, field: string, option: string) =>
  dialog.getByRole("group", { name: field, exact: true }).getByRole("button", { name: option, exact: true })

/* The priority is a score from 0 to 100, typed into its box. */
const score = (dialog: ReturnType<Page["getByRole"]>) =>
  dialog.getByRole("spinbutton", { name: "Priority, from 0 to 100" })

test("a new ticket carries its priority, type and model, and Ctrl+Enter launches it", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f00d", title: "Announce it" } })
  })
  const dialog = await open(page)

  await expect(dialog.getByText("Launched, the ticket starts at the next pass")).toBeVisible()
  await expect(dialog.getByText("Ready to run")).toHaveCount(0)
  await score(dialog).fill("80")
  await expect(dialog.locator('[data-slot="priority-input"] [data-slot="priority-badge"]')).toHaveText("80")
  await segment(dialog, "Type", "Code").click()
  await choose(page, dialog, "Model", "haiku")
  await segment(dialog, "Sub-type", "Bug").click()
  await dialog.getByLabel("Title").fill("Announce it")
  await page.screenshot({ path: "test-results/new-ticket.png" })
  await dialog.getByLabel("Title").press("Control+Enter")

  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toMatchObject({
    title: "Announce it",
    priority: 80,
    type: "code",
    model: "haiku",
    subtype: "bug",
    ready: true,
  })
  await expect(dialog).toBeHidden()
})

test("the sub-type is a code ticket's: shown for Code, hidden for any other type", async ({ page }) => {
  const dialog = await open(page)
  const subtype = dialog.getByRole("group", { name: "Sub-type", exact: true })
  await expect(subtype).toHaveCount(0)
  await segment(dialog, "Type", "Code").click()
  await expect(subtype).toBeVisible()
  await segment(dialog, "Sub-type", "Feature").click()
  await segment(dialog, "Type", "Writing").click()
  await expect(subtype).toHaveCount(0)
  await segment(dialog, "Type", "Code").click()
  await expect(subtype).toBeVisible()
  // Taken away with the type it belonged to.
  await expect(segment(dialog, "Sub-type", "Feature")).toHaveAttribute("aria-pressed", "false")
})

test("no card says what the ticket will come back as, whatever the type", async ({ page }) => {
  const dialog = await open(page)
  const project = dialog.getByRole("combobox", { name: "Project" })
  await project.click()
  await page.getByRole("option", { name: /Website/ }).click()
  await expect(dialog.locator('[data-slot="project-repository"]')).toHaveText("git")

  for (const type of ["Auto", "Code", "Writing", "External action", "Publication"]) {
    await segment(dialog, "Type", type).click()
    await expect(dialog.locator('[data-slot="ticket-outcome"]')).toHaveCount(0)
    await expect(dialog.getByText("What it will give")).toHaveCount(0)
  }
})

test("Draft creates a ticket the runner leaves alone", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f011", title: "Later" } })
  })
  const dialog = await open(page)
  await dialog.getByLabel("Title").fill("Later")
  await score(dialog).fill("0")
  await dialog.getByRole("button", { name: "Draft" }).click()
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toMatchObject({ title: "Later", priority: 0, ready: false })
  await expect(dialog).toBeHidden()
})

test("a priority outside 0 to 100 is said under its field and never sent", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f013", title: "Too much" } })
  })
  const dialog = await open(page)
  await dialog.getByLabel("Title").fill("Too much")
  await score(dialog).fill("150")
  await expect(dialog.getByText("A priority is a number from 0 to 100.").first()).toBeVisible()
  await dialog.getByRole("button", { name: "Launch the ticket" }).click()
  await expect(dialog).toBeVisible()
  expect(sent).toHaveLength(0)
})

test("a draft refused for want of a title, then launched with Ctrl+Enter, is launched", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f012", title: "Now" } })
  })
  const dialog = await open(page)
  await dialog.getByRole("button", { name: "Draft" }).click()
  await expect(dialog.getByLabel("Title")).toHaveAttribute("aria-invalid", "true")
  expect(sent).toHaveLength(0)
  await dialog.getByLabel("Title").fill("Now")
  await dialog.getByLabel("Title").press("Control+Enter")
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toMatchObject({ title: "Now", ready: true })
})

test("left alone, the three say nothing and the type is the runner's to deduce", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f00e", title: "Plain" } })
  })
  const dialog = await open(page)
  await dialog.getByLabel("Title").fill("Plain")
  await dialog.getByRole("button", { name: "Launch the ticket" }).click()
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toMatchObject({ priority: "", type: "", model: "", subtype: "", ready: true })
})

test("Ctrl+Enter from the brief creates the ticket with the last words typed", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f00f", title: "Briefed" } })
  })
  const dialog = await open(page)
  await dialog.getByLabel("Title").fill("Briefed")
  await dialog.locator(".ProseMirror").click()
  await page.keyboard.type("The last words")
  await page.keyboard.press("Control+Enter")
  await expect.poll(() => sent.length).toBe(1)
  expect(String(sent[0].body)).toContain("The last words")
})

/* The project is typed into rather than scrolled through: the field is reached
 * with Tab, a letter opens the list filtered by it, the arrows
 * walk it, Enter takes the highlighted project and Escape closes the list and
 * leaves the dialog — the whole ticket made without the mouse. */
test("the project is chosen from the keyboard, filtered by what is typed", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f010", title: "Typed" } })
  })
  const dialog = await open(page)
  await dialog.getByLabel("Title").fill("Typed")
  const project = dialog.getByRole("combobox", { name: "Project" })

  // Reached by Tab like any field — here from the one after it, since the
  // brief's editor before it keeps Tab for its own lists.
  await segment(dialog, "Type", "Auto").focus()
  await page.keyboard.press("Shift+Tab")
  await expect(project).toBeFocused()
  await page.keyboard.press("ArrowDown")
  const list = page.getByRole("listbox")
  await expect(list.getByRole("option")).toHaveCount(4)
  const first = await list.getByRole("option", { selected: true }).textContent()
  await page.keyboard.press("ArrowDown")
  await expect(list.getByRole("option", { selected: true })).not.toHaveText(first ?? "")
  await page.keyboard.press("ArrowUp")
  await expect(list.getByRole("option", { selected: true })).toHaveText(first ?? "")
  await page.keyboard.press("Escape")
  await expect(list).toBeHidden()
  await expect(dialog).toBeVisible()

  await expect(project).toBeFocused()
  await page.keyboard.type("news")
  await expect(page.getByRole("combobox").and(page.locator("[cmdk-input]"))).toHaveValue("news")
  await expect(list.getByRole("option", { selected: true })).toContainText("Newsletter")
  await page.keyboard.press("Enter")
  await expect(list).toBeHidden()
  await expect(project).toContainText("Newsletter")
  await page.keyboard.press("Control+Enter")

  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toMatchObject({ title: "Typed", project: "0000000000000000000000000000beef" })
})
