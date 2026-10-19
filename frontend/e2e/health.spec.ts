import { expect, test, type Page, type Route } from "@playwright/test"

/* The installation's health, at the top of the dashboard.
 *
 * The checks themselves are the server's (`health.py`, held by tests/run.py);
 * here the answer is given, so that what is checked is what somebody sees: a
 * red board draws the band with each problem's cause and its way out, a fix is
 * asked for before it is made, the band goes when the recheck is green, and a
 * green board never draws it. Set `PONOS_E2E_SHOTS` to a folder to keep a
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

async function open(page: Page, answers: unknown[], fixed: string[] = []) {
  let asked = 0
  await page.route("**/api/health", (route: Route) =>
    route.fulfill({ json: answers[Math.min(asked++, answers.length - 1)] })
  )
  await page.route("**/api/health/fix", (route: Route) => {
    fixed.push(route.request().postData() ?? "")
    return route.fulfill({ json: { done: "added Progress, Runner", ...GREEN } })
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
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
  await expect(repository.getByRole("link")).toHaveAttribute("href", /installations\/new/)
  await expect(repository.getByRole("listitem")).toHaveCount(1)
  await expect(band.locator('[data-code="claude.login"]')).toContainText("claude auth login")
  await expect(band.locator('[data-code="notion.token"]')).toHaveCount(0)
  await shot(page, "health-red")

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
