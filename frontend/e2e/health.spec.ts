import { expect, test, type Page, type Route } from "@playwright/test"

/* The installation's health, at the top of the dashboard.
 *
 * The checks themselves are the server's (`health.py`, held by tests/run.py);
 * here the answer is given, so that what is checked is what somebody sees: a
 * red board draws the band folded on one line, unfolded one line per problem,
 * each with a detail of its own (cause, steps), a fix is asked for before it is
 * made, the band goes when the recheck is green, and a green board never draws
 * it. Set `PONOS_E2E_SHOTS` to a folder to keep a
 * capture of each state.
 */

const check = (code: string, state: "ok" | "warn" | "error", extra: Record<string, unknown> = {}) => ({
  code,
  group: code.split(".")[0],
  state,
  title: code,
  said: code,
  params: {},
  cause: "",
  steps: [],
  url: "",
  evidence: "",
  notes: [],
  fix: null,
  ...extra,
})

const RED = {
  checks: [
    check("notion.token", "ok", { title: "Notion token", said: "Connected as “{{name}}”.", params: { name: "Ponos" } }),
    check("notion.columns", "error", {
      title: "Tickets properties",
      said: "Properties missing on the tickets database: {{missing}}.",
      params: { missing: "“Runner”, “Progress”" },
      cause: "The board predates a version of Ponos, or a property was renamed or retyped.",
      notes: [
        { name: "Runner", said: ["which machine took a ticket is not written — fine on one machine, but a second one on this board would put back the tickets the first is running"] },
        { name: "Progress", said: ["nothing says what a session is doing while it runs"] },
      ],
      fix: {
        action: "notion_columns",
        label: "Configure",
        confirm: "Add {{missing}} to the tickets database? Existing properties are left as they are.",
        missing: "“Runner”, “Progress”",
        target: "",
      },
    }),
    check("github.repository", "error", {
      title: "GitHub rights on {{repository}}",
      said: "The GitHub App does not reach {{repository}}.",
      params: { repository: "acme/site" },
      cause: "The App is installed without this repository, or on another account.",
      steps: ["Install the GitHub App on this repository: choose it in the installation's list."],
      url: "https://github.com/apps/ponos/installations/new",
    }),
    check("claude.login", "error", {
      title: "Claude connection",
      said: "Claude Code is not signed in.",
      cause: "No account was connected to the CLI on this machine.",
      steps: ["In a terminal on this machine, run `claude auth login` and follow the link."],
    }),
    check("projects.branch", "warn", {
      title: "Default branch of {{project}}",
      said: "The default branch of {{project}} is not known: {{branch}} is assumed.",
      params: { project: "Website", branch: "main" },
    }),
    check("machine.disk", "ok", { title: "Disk space", said: "{{free}} MB free.", params: { free: "90000" } }),
  ],
  problems: 3,
  checked_at: new Date().toISOString(),
}
const GREEN = { checks: RED.checks.map((one) => ({ ...one, state: "ok", fix: null })), problems: 0, checked_at: RED.checked_at }

async function open(page: Page, answers: unknown[], fixed: string[] = [], unfolded = true) {
  let asked = 0
  await page.route("**/api/health", (route: Route) =>
    route.fulfill({ json: answers[Math.min(asked++, answers.length - 1)] })
  )
  await page.route("**/api/health/fix", (route: Route) => {
    fixed.push(route.request().postData() ?? "")
    return route.fulfill({ json: { done: "added Progress, Runner", ...GREEN } })
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  // Folded is the default; a test that wants the lines asks for them.
  if (unfolded) await page.addInitScript(() => localStorage.setItem("ponos-health-open", "open"))
  await page.goto("/")
  await expect(page.getByText("A long ticket").filter({ visible: true }).first()).toBeVisible()
}

const shot = async (page: Page, name: string) => {
  if (process.env.PONOS_E2E_SHOTS) await page.screenshot({ path: `${process.env.PONOS_E2E_SHOTS}/${name}.png` })
}

test("a red installation draws each problem with its way out, and a green one draws nothing", async ({ page }) => {
  await open(page, [RED, GREEN])
  const band = page.getByTestId("health-band")
  await expect(band).toBeVisible()
  await expect(band.getByTestId("health-check")).toHaveCount(4)
  const columns = band.locator('[data-code="notion.columns"]')
  await expect(columns.getByTestId("health-fix")).toBeVisible()
  const repository = band.locator('[data-code="github.repository"]')
  await expect(repository.getByRole("link", { name: "Open the link" })).toHaveAttribute("href", /installations\/new/)
  await expect(band.locator('[data-code="notion.token"]')).toHaveCount(0)
  await shot(page, "health-red")

  // The steps and the cause are behind each problem's own toggle.
  const login = band.locator('[data-code="claude.login"]')
  await expect(login.getByTestId("health-detail")).toBeHidden()
  await login.getByTestId("health-detail-toggle").click()
  await expect(login.getByTestId("health-detail")).toContainText("claude auth login")
  await shot(page, "health-detail")

  await band.getByTestId("health-recheck").click()
  await expect(page.getByTestId("health-band")).toHaveCount(0)
  await shot(page, "health-green")
})

test("a fix is made only once it is confirmed", async ({ page }) => {
  const fixed: string[] = []
  await open(page, [RED], fixed)
  const columns = page.locator('[data-code="notion.columns"]')
  await columns.getByTestId("health-fix").click()
  const dialog = page.getByRole("alertdialog")
  await expect(dialog).toContainText("“Runner”, “Progress”")
  await shot(page, "health-confirm")
  await dialog.getByRole("button", { name: "Cancel" }).click()
  // Gone, not closing: a second click under its fading overlay finds nothing.
  await expect(page.getByRole("alertdialog")).toHaveCount(0)
  expect(fixed).toEqual([])

  await columns.getByTestId("health-fix").click()
  await page.getByRole("alertdialog").getByRole("button", { name: "Configure" }).click()
  await expect(page.getByTestId("health-band")).toHaveCount(0)
  expect(fixed).toHaveLength(1)
  expect(JSON.parse(fixed[0])).toEqual({ action: "notion_columns", target: "", confirmed: true })
})

test("a green installation never draws the band", async ({ page }) => {
  await open(page, [GREEN])
  await expect(page.getByTestId("health-band")).toHaveCount(0)
})

test("the band is one line by default, opens by keyboard and the choice is kept", async ({ page }) => {
  await open(page, [RED], [], false)
  const band = page.getByTestId("health-band")
  const toggle = band.getByTestId("health-toggle")
  await expect(toggle).toHaveAttribute("aria-expanded", "false")
  await expect(band.getByTestId("health-check")).toHaveCount(0)
  await expect(band.getByTestId("health-recheck")).toBeVisible()
  expect((await band.boundingBox())?.height).toBeLessThan(80)
  await shot(page, "health-folded")

  await toggle.focus()
  await page.keyboard.press("Enter")
  await expect(band.getByTestId("health-check")).toHaveCount(4)
  await page.reload()
  await expect(page.getByTestId("health-band").getByTestId("health-check")).toHaveCount(4)
  await page.getByTestId("health-toggle").click()
  await expect(page.getByTestId("health-band").getByTestId("health-check")).toHaveCount(0)
})

test("the detail of a problem names each property once, and the raw error only there", async ({ page }) => {
  await open(page, [RED])
  const columns = page.locator('[data-code="notion.columns"]')
  await columns.getByTestId("health-detail-toggle").focus()
  await page.keyboard.press("Enter")
  const detail = columns.getByTestId("health-detail")
  await expect(detail.getByRole("listitem")).toHaveCount(2)
  await expect(detail).toContainText("“Runner”")
})

test("the band arriving late does not move the page", async ({ page }) => {
  let release: () => void = () => {}
  const late = new Promise<void>((resolve) => (release = resolve))
  await page.route("**/api/health", async (route: Route) => {
    await late
    await route.fulfill({ json: RED })
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  // The ticket's card, not the first text that says its title: a notification
  // names it too, and which comes first changes with the band.
  const card = page.locator('[data-ticket-card="000000000000000000000000000abcde"]')
  await expect(card).toBeVisible()
  // The board is still loading around the card: what is measured is where it stays.
  let last = ""
  await expect
    .poll(async () => {
      const now = JSON.stringify(await card.boundingBox())
      const settled = now === last
      last = now
      return settled
    })
    .toBe(true)
  const before = await card.boundingBox()
  expect(await page.getByTestId("health-band").count()).toBe(0)

  release()
  await expect(page.getByTestId("health-band")).toBeVisible()
  const after = await card.boundingBox()
  expect(after?.y).toBe(before?.y)
})

test("in French, the checks' own sentences arrive with the band, fetched apart", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("ponos-language", "fr"))
  const fetched: string[] = []
  page.on("request", (request) => {
    if (/health-french-[^/]+\.js$/.test(request.url())) fetched.push(request.url())
  })
  await open(page, [RED])
  const columns = page.locator('[data-code="notion.columns"]')
  await expect(columns).toContainText("Propriétés manquantes sur la base de tickets : “Runner”, “Progress”.")
  await expect(page.getByTestId("health-toggle")).toContainText("4 points à corriger")
  expect(fetched).toHaveLength(1)
})

test("the band shows what the server itself found: a schedule nobody fired, nothing merely said", async ({ page }) => {
  // Not answered here: the console's own checks, on its board of files, whose
  // "Weekly digest" has been due for weeks — what `ponos doctor` used to be
  // alone to say.
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.addInitScript(() => localStorage.setItem("ponos-health-open", "open"))
  await page.goto("/")
  const band = page.getByTestId("health-band")
  const late = band.locator('[data-code="notion.schedule"]')
  await expect(late).toBeVisible({ timeout: 30_000 })
  await expect(late).toHaveAttribute("data-state", "error")
  await expect(late).toContainText("Weekly digest")
  await expect(band.locator('[data-code="notion.schedule"]')).toHaveCount(1)
  // A setting said rather than judged is `doctor`'s grey line, never one of these.
  await expect(band.locator('[data-state="info"], [data-state="ok"]')).toHaveCount(0)
  await shot(page, "health-server")
})
