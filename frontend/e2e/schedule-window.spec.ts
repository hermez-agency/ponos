import { expect, test, type Page } from "@playwright/test"

/* The window a schedule is written in, read in French.
 *
 * A dialog in the middle of the list rather than a drawer against its edge:
 * Escape and the cross close it and give the cursor back to the button that
 * opened it, the cadence is one press, the day takes the shape the cadence
 * gives it, and the line under them says when the next ticket is born — on a
 * Friday morning, next Monday. The creation itself is answered by the test, not
 * the board: a schedule more is one more row for `schedules.spec.ts` to count.
 */

const LIST = "/?view=console/schedules/list"

test.use({ locale: "fr-FR", timezoneId: "Europe/Paris" })

async function open(page: Page) {
  await page.clock.setFixedTime(new Date("2026-10-16T10:00:00+02:00"))
  // The hours are the runner's, and the machine running these tests may be in
  // any zone: this one is said to be in Paris, as the browser is.
  await page.route(/\/api\/schedules$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    try {
      const response = await route.fetch()
      await route.fulfill({ response, json: { ...(await response.json()), timezone: "Europe/Paris" } })
    } catch {
      // The list read again after a save, still on its way when the test ends.
    }
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await expect(page.getByText("Test email")).toBeVisible()
  const button = page.getByText("Nouvelle récurrence")
  await button.click()
  const window_ = page.getByRole("dialog")
  await expect(window_.getByText("Titre du ticket")).toBeVisible()
  return window_
}

test("a new schedule opens in a modal window, and Escape gives the focus back", async ({ page }) => {
  const window_ = await open(page)
  await expect(window_).toHaveAttribute("aria-modal", "true")
  await expect(window_.locator('[data-slot="dialog-title"]')).toHaveText("Nouveau ticket récurrent")
  await expect(window_.getByText("Ponos crée ce ticket automatiquement, à la cadence choisie.")).toBeVisible()
  const width = (await window_.boundingBox())!.width
  expect(width).toBeLessThanOrEqual(620)
  expect(width).toBeGreaterThan(560)
  // Tab stays inside the window.
  for (let press = 0; press < 30; press++) {
    await page.keyboard.press("Tab")
    expect(await window_.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press("Escape")
  await expect(window_).not.toBeAttached()
  await expect(page).toHaveURL(/schedules\/list$|schedules\/list[^/]*$/)
  await expect(page.locator(":focus")).toContainText("Nouvelle récurrence")
})

test("the cross closes it too", async ({ page }) => {
  const window_ = await open(page)
  await window_.getByRole("button", { name: "Fermer" }).click()
  await expect(window_).not.toBeAttached()
})

test("the day takes the shape of the cadence, and the summary follows", async ({ page }) => {
  const window_ = await open(page)
  const summary = window_.locator('[data-slot="recurrence-summary"]')
  await expect(window_.getByRole("button", { name: "Chaque semaine" })).toHaveAttribute("aria-pressed", "true")
  await expect(window_.getByRole("button", { name: "lundi" })).toHaveAttribute("aria-pressed", "true")
  await expect(window_.locator('input[type="time"]')).toHaveValue("09:00")
  await expect(summary).toHaveText(
    "Chaque lundi à 09:00. Prochain ticket, une fois activée : lun. 19 oct. à 09:00."
  )

  await window_.getByRole("button", { name: "mercredi" }).click()
  await expect(summary).toContainText("Chaque mercredi à 09:00.")
  await expect(summary).toContainText("mer. 21 oct.")

  await window_.getByRole("button", { name: "Chaque mois" }).click()
  await expect(window_.getByRole("button", { name: "lundi" })).toHaveCount(0)
  const day = window_.getByRole("spinbutton", { name: /Jour/ })
  await expect(day).toHaveValue("1")
  await day.fill("20")
  await window_.locator('input[type="time"]').fill("14:30")
  await expect(summary).toContainText("Le 20 de chaque mois à 14:30.")
  await expect(summary).toContainText("mar. 20 oct. à 14:30")

  await window_.getByRole("button", { name: "Chaque jour" }).click()
  await expect(day).toHaveCount(0)
  await expect(summary).toContainText("Chaque jour à 14:30.")
  await expect(summary).toContainText("ven. 16 oct. à 14:30")
})

test("the model is the chat's picker, the priority a score with its badge", async ({ page }) => {
  const window_ = await open(page)
  const priority = window_.getByRole("spinbutton", { name: "Priorité, de 0 à 100" })
  await expect(priority).toHaveAttribute("placeholder", "50")
  await priority.fill("90")
  await expect(priority).toHaveValue("90")
  // The chat's own picker: Claude's models first, the empty one letting go —
  // the ticket then takes the runner's model.
  const model = window_.locator("[data-model-choice]")
  await model.click()
  for (const word of ["haiku", "sonnet", "opus"])
    await expect(page.locator(`[data-model-option="${word}"]`)).toBeVisible()
  await page.locator('[data-model-option="opus"]').click()
  await expect(model).toHaveText("Opus")
  await model.click()
  await page.locator('[data-model-option=""]').click()
  await expect(model).not.toHaveText("Opus")
})

/* What the page sends, answered here. */
async function creation(page: Page) {
  const sent: { url: string; body: Record<string, unknown> }[] = []
  await page.route(/\/api\/schedules(\/new0000)?$/, async (route) => {
    const request = route.request()
    if (request.method() !== "POST") return route.fallback()
    sent.push({ url: request.url(), body: request.postDataJSON() })
    await route.fulfill({ json: { id: "new0000", name: "Revue" } })
  })
  return sent
}

test("unticked, the new schedule is written as it always was: off", async ({ page }) => {
  const sent = await creation(page)
  const window_ = await open(page)
  await window_.getByPlaceholder("Revue hebdomadaire des dépendances").fill("Revue")
  await window_.getByRole("button", { name: "Créer la récurrence" }).click()
  await expect(window_).not.toBeAttached()
  expect(sent).toHaveLength(1)
  expect(sent[0].body).toMatchObject({ name: "Revue", cadence: "Weekly", day: "Monday", at: "09:00" })
})

test("ticked, it is turned on once it exists", async ({ page }) => {
  const sent = await creation(page)
  const window_ = await open(page)
  await window_.getByPlaceholder("Revue hebdomadaire des dépendances").fill("Revue")
  await window_.getByRole("button", { name: "Chaque jour" }).click()
  await window_.getByRole("checkbox", { name: "Activer tout de suite" }).click()
  await expect(window_.locator('[data-slot="recurrence-summary"]')).toContainText("Prochain ticket : sam. 17 oct. à 09:00.")
  await window_.getByRole("button", { name: "Créer la récurrence" }).click()
  await expect(window_).not.toBeAttached()
  expect(sent).toHaveLength(2)
  expect(sent[0].body).toMatchObject({ name: "Revue", cadence: "Daily", at: "09:00" })
  expect(sent[1].url).toMatch(/\/api\/schedules\/new0000$/)
  expect(sent[1].body).toEqual({ active: true })
})

test("on a phone the window is the whole screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const window_ = await open(page)
  await expect
    .poll(async () => {
      const box = await window_.boundingBox()
      return box && [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)]
    })
    .toEqual([0, 0, 390, 844])
  await expect(window_.getByRole("button", { name: "Créer la récurrence" })).toBeInViewport()
})

test("an opened schedule is the same window, saved with its box", async ({ page }) => {
  const saved: Record<string, unknown>[] = []
  await page.route(/\/api\/schedules\/[0-9a-f]+$/, async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    saved.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "x" } })
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await page.getByRole("link", { name: "Test email" }).click()
  const window_ = page.getByRole("dialog")
  await expect(window_.locator('[data-slot="dialog-title"]')).toHaveText("Modifier la récurrence")
  await expect(window_.getByRole("button", { name: "Chaque heure" })).toHaveAttribute("aria-pressed", "true")
  const box = window_.getByRole("checkbox", { name: "Activée" })
  await expect(box).not.toBeChecked()
  await box.click()
  await window_.getByRole("button", { name: "Enregistrer" }).click()
  await expect.poll(() => saved.length).toBe(1)
  expect(saved[0]).toMatchObject({ name: "Test email", cadence: "Hourly", active: true })
})

test("the type its tickets are born with is a button, and code says its sub-type too", async ({ page }) => {
  const sent = await creation(page)
  const window_ = await open(page)
  await window_.getByPlaceholder("Revue hebdomadaire des dépendances").fill("Revue")
  const type = window_.getByRole("group", { name: "Type", exact: true })
  const subtype = window_.getByRole("group", { name: "Sous-type", exact: true })
  await expect(type.getByRole("button")).toHaveCount(4)
  // Empty, the runner deduces each ticket's: the sub-type may still be said.
  await expect(subtype).toBeVisible()
  await type.getByRole("button").nth(1).click()
  await expect(subtype).not.toBeAttached()
  const code = type.getByRole("button", { name: "Code", exact: true })
  await code.click()
  await expect(code).toHaveAttribute("aria-pressed", "true")
  await subtype.getByRole("button", { name: /Bug/ }).click()
  await window_.getByRole("button", { name: "Créer la récurrence" }).click()
  await expect(window_).not.toBeAttached()
  expect(sent[0].body).toMatchObject({ name: "Revue", type: "code", subtype: "bug" })
})

/* The project its tickets are for: chosen as a new ticket's is, from the
 * board's projects. Without one, every ticket the schedule makes comes back as
 * a document — a schedule of code work could only be written in Notion. */
const WEBSITE = "0000000000000000000000000000cafe"
// Neither renamed by `projects.spec.ts`, which shares this board.
const JOURNAL = "0000000000000000000000000000f00d"

test("the project its tickets are for is chosen, written, and said by the list", async ({ page }) => {
  const sent = await creation(page)
  const window_ = await open(page)
  // Read again after the creation, the list holds the new row: answered here,
  // with the page the server would have written and no name, as it says one
  // whose project it has not read yet.
  await page.route(/\/api\/schedules$/, async (route) => {
    if (route.request().method() !== "GET" || !sent.length) return route.fallback()
    try {
      const response = await route.fetch()
      const body = await response.json()
      const made = { ...body.schedules[0], id: "new0000", name: "Revue", url: "", active: false, project: "", project_id: WEBSITE, problem: "" }
      await route.fulfill({ response, json: { ...body, timezone: "Europe/Paris", schedules: [...body.schedules, made] } })
    } catch {
      // Read again once more, still on its way when the test ends.
    }
  })
  await window_.getByPlaceholder("Revue hebdomadaire des dépendances").fill("Revue")
  const project = window_.getByRole("combobox", { name: "Projet" })
  await project.click()
  await page.getByRole("option", { name: /Website/ }).click()
  await expect(project).toContainText("Website")
  await expect(window_.locator('[data-slot="project-repository"]')).toHaveText("git")
  await window_.getByRole("button", { name: "Créer la récurrence" }).click()
  await expect(window_).not.toBeAttached()
  expect(sent[0].body).toMatchObject({ name: "Revue", project: WEBSITE })
  await expect(page.locator('[data-slot="table-row"]', { hasText: "Revue" })).toContainText("Website")
})

test("opened from a project, the new schedule is for that project", async ({ page }) => {
  const sent = await creation(page)
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(`${LIST}&filter=${encodeURIComponent(JSON.stringify({ project: JOURNAL }))}`)
  await page.getByText("Nouvelle récurrence").click()
  const window_ = page.getByRole("dialog")
  await expect(window_.getByRole("combobox", { name: "Projet" })).toContainText("Journal")
  await window_.getByPlaceholder("Revue hebdomadaire des dépendances").fill("Revue")
  await window_.getByRole("button", { name: "Créer la récurrence" }).click()
  await expect(window_).not.toBeAttached()
  expect(sent[0].body).toMatchObject({ name: "Revue", project: JOURNAL })
})

test("an opened schedule changes project", async ({ page }) => {
  const saved: Record<string, unknown>[] = []
  await page.route(/\/api\/schedules\/[0-9a-f]+$/, async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    saved.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "x" } })
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await page.getByRole("link", { name: "Test email" }).click()
  const window_ = page.getByRole("dialog")
  const project = window_.getByRole("combobox", { name: "Projet" })
  await project.click()
  await page.getByRole("option", { name: /Journal/ }).click()
  await window_.getByRole("button", { name: "Enregistrer" }).click()
  await expect.poll(() => saved.length).toBe(1)
  expect(saved[0]).toMatchObject({ name: "Test email", project: JOURNAL })
})
