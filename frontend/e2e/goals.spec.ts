import { expect, test } from "@playwright/test"

/* The goals, written from the console: created, changed, tied to a ticket and
 * closed or deleted — each one a request the board takes, and a card the list shows.
 *
 * Served by the console the project deletions have: a goal more is one more
 * card, and a ticket tied to it is a ticket the others would see change.
 */

const LIST = "/?view=console/goals/list"

test.use({ locale: "fr-FR" })
test.describe.configure({ mode: "serial" })

test.beforeEach(async ({ page }) => {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
})

test("a goal is created from the list, then changed, and both show", async ({ page }) => {
  await page.goto(LIST)
  await page.getByText("Nouvel objectif").first().click()
  const form = page.getByRole("dialog")
  await form.getByLabel("Nom").fill("Lancer la v1")
  await form.getByLabel("Description").fill("La première version")
  await form.getByLabel("Terminée quand").fill("Dix clients payants")
  await form.getByLabel("Échéance").fill("2026-12-31")
  await form.getByRole("button", { name: "Website" }).click()
  await form.getByRole("button", { name: /Ticket 3$/ }).click()
  await form.getByRole("button", { name: "Enregistrer" }).click()

  const card = page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v1" })
  await expect(card).toBeVisible()
  await expect(card).toContainText("Dix clients payants")
  await expect(card).toContainText("0 sur 1 ticket fait")
  await expect(card.locator('[data-slot="goals-title"]')).toBeVisible()

  // The pencil is a target of 24 px at least, named after its goal.
  const pencil = card.getByRole("link", { name: "Modifier l'objectif « Lancer la v1 »" })
  const box = await pencil.locator('[data-slot="goals-edit"]').boundingBox()
  expect(box?.width).toBeGreaterThanOrEqual(24)
  expect(box?.height).toBeGreaterThanOrEqual(24)
  await pencil.click()
  const edit = page.getByRole("dialog")
  await edit.getByLabel("Nom").fill("Lancer la v2")
  await edit.getByRole("button", { name: "Enregistrer" }).click()
  await expect(page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v2" })).toBeVisible()
  await expect(page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v1" })).toHaveCount(0)
})

test("a goal's page lists its tickets by column, and makes one more for it", async ({ page }) => {
  await page.goto(LIST)
  // Anywhere on the card opens the goal, not only its title.
  const card = page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v2" })
  const box = await card.boundingBox()
  await card.click({ position: { x: 24, y: (box?.height ?? 0) - 16 } })
  const listed = page.locator('[data-slot="goal-tickets"]')
  const row = listed.locator("[data-goal-ticket]", { hasText: "Ticket 3" })
  await expect(row).toBeVisible()
  const column = listed.locator("[data-goal-column]", { has: page.locator("[data-goal-ticket]", { hasText: "Ticket 3" }) })
  await expect(column).toContainText("1")

  await listed.locator('[data-slot="goal-new-ticket"]').click()
  const form = page.getByRole("dialog", { name: "Nouveau ticket" })
  await expect(form).toBeVisible()
  await expect(form).toContainText("Lancer la v2")
  // Back on the goal's page, which the form was opened over.
  await page.goBack()
  await row.getByRole("link").click()
  await expect(page.getByRole("dialog").locator('[data-slot="ticket-goal"]')).toContainText("Lancer la v2")
})

test("a goal's page leads to the board filtered on it, and its card says the goal", async ({ page }) => {
  await page.goto(LIST)
  await page.locator('[data-slot="goals-title"]', { hasText: "Lancer la v2" }).click()
  await page.locator('[data-slot="goal-board"]').click()
  await expect(page).toHaveURL(/[?&]goal=[0-9a-f-]+/)
  const cards = page.locator("[data-ticket-card]")
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText("Ticket 3")
  await expect(cards.first().locator('[data-slot="ticket-card-goal"]')).toHaveText("Lancer la v2")
  await expect(page.locator('[data-slot="search-count"]')).toContainText("1 /")
})

test("the ticket names its goal, and another can be chosen from it", async ({ page }) => {
  await page.goto("/?view=console/tickets/list")
  await page.getByRole("link", { name: /Ticket 3$/ }).first().click()
  const window_ = page.getByRole("dialog")
  await expect(window_.locator('[data-slot="ticket-goal"]')).toContainText("Lancer la v2")
  await window_.locator('[data-slot="ticket-goal-select"]').click()
  await page.getByRole("option", { name: "Aucun objectif" }).click()
  await expect(window_.locator('[data-slot="ticket-goal"]')).toHaveCount(0)

  await page.goto(LIST)
  await expect(page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v2" })).toContainText("0 sur 0 ticket")
})

test("a ticket of a goal moved elsewhere moves its progress on the open page", async ({ page }) => {
  // Written as another tab would: the page open here draws nothing of it itself.
  const write = (path: string, data: Record<string, unknown>) =>
    page.request.post(path, { headers: { "X-Ponos": "1" }, data })
  const ticket = `${7}`.padStart(32, "0")
  const made = await write("/api/goals", { name: "Ouvrir la boutique", tickets: [ticket] })
  expect(made.ok()).toBeTruthy()

  await page.goto(LIST)
  const card = page.locator('[data-slot="goals-item"]', { hasText: "Ouvrir la boutique" })
  await expect(card).toContainText("0 sur 1 ticket fait")

  expect((await write(`/api/tickets/${ticket}/status`, { column: "done" })).ok()).toBeTruthy()
  await expect(card).toContainText("1 sur 1 ticket fait", { timeout: 15_000 })

  // Tied from the ticket's window, elsewhere, while the goal's page is open: the server says `goals`.
  await card.locator('[data-slot="goals-title"]').click()
  const listed = page.locator('[data-slot="goal-tickets"]')
  await expect(listed.locator("[data-goal-ticket]", { hasText: "Ticket 7" })).toBeVisible()
  expect((await write(`/api/tickets/${`${8}`.padStart(32, "0")}/goal`, { goal: (await made.json()).id })).ok()).toBeTruthy()
  await expect(listed.locator("[data-goal-ticket]", { hasText: "Ticket 8" })).toBeVisible({ timeout: 15_000 })
  await page.goBack()
  await expect(card).toContainText("1 sur 2 tickets faits")
})

test("a goal marked reached leaves the list, and comes back under every status", async ({ page }) => {
  await page.goto(LIST)
  await page.locator('[data-slot="goals-title"]', { hasText: "Ouvrir la boutique" }).click()
  const whole = page.locator('[data-slot="goals-page"]')
  await whole.locator('[data-close-goal="atteint"]').click()
  await expect(whole).toContainText("atteint")
  await expect(whole.locator('[data-close-goal="atteint"]')).toHaveCount(0)
  await expect(whole).toContainText("1 sur 2 tickets faits")

  await page.goto(LIST)
  const card = page.locator('[data-slot="goals-item"]', { hasText: "Ouvrir la boutique" })
  await expect(page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v2" })).toBeVisible()
  await expect(card).toHaveCount(0)
  await page.locator('[data-slot="goals-status-filter"]').click()
  await page.getByRole("option", { name: "Tous les statuts" }).click()
  await expect(card).toBeVisible()
  await expect(card).toContainText("1 sur 2 tickets faits")
})

test("a goal is deleted after a confirmation that says so", async ({ page }) => {
  await page.goto(LIST)
  await page.locator('[data-slot="goals-title"]', { hasText: "Lancer la v2" }).click()
  await page.locator("[data-delete-goal]").click()
  const dialog = page.getByRole("alertdialog")
  await expect(dialog).toContainText("Supprimer « Lancer la v2 » ?")
  await expect(dialog).toContainText("corbeille")
  await dialog.getByRole("button", { name: "Annuler" }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator("[data-delete-goal]")).toBeVisible()
  await page.locator("[data-delete-goal]").click()
  await page.getByRole("alertdialog").getByRole("button", { name: "Supprimer l'objectif" }).click()
  await expect(page.locator('[data-slot="goals-item"]', { hasText: "Lancer la v2" })).toHaveCount(0)
})

test("a refused write says why", async ({ page }) => {
  await page.route(/\/api\/goals$/, async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    await route.fulfill({ status: 400, json: { error: "this workspace has no goals database" } })
  })
  await page.goto(LIST)
  await page.getByText("Nouvel objectif").first().click()
  const form = page.getByRole("dialog")
  await form.getByLabel("Nom").fill("Refusé")
  await form.getByRole("button", { name: "Enregistrer" }).click()
  await expect(page.getByText("Cet espace de travail n'a pas de base d'objectifs.").first()).toBeVisible()
})

test("without a goals database, no goal is offered to write, and the empty list says why", async ({ page }) => {
  await page.route(/\/api\/goals$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { goals: [], configured: false } })
  })
  await page.goto(LIST)
  await expect(page.getByText("Aucun objectif.")).toBeVisible()
  await expect(page.getByText("L'espace de travail n'a pas de base Objectifs", { exact: false })).toBeVisible()
  await expect(page.getByText("Nouvel objectif")).toHaveCount(0)
})

test("an empty goals database offers to write the first goal", async ({ page }) => {
  await page.route(/\/api\/goals$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { goals: [], configured: true } })
  })
  await page.goto(LIST)
  await expect(page.getByText("Aucun objectif.")).toBeVisible()
  await expect(page.getByText("Notion", { exact: false })).toHaveCount(0)
  await page.locator('[data-slot="goals-new"]').click()
  await expect(page.getByRole("dialog").getByLabel("Nom")).toBeVisible()
})
