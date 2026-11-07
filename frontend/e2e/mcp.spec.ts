import { expect, test, type Page } from "@playwright/test"

/* The settings' MCP tab: what an MCP is, the wizard that fills in this
 * console's own address, the connection test, and the servers a session holds.
 * The real test runs against the real console (it is the one thing that tells
 * a live server apart); a failing one, and the list of servers — which needs a
 * Claude Code with servers — are answered by the page's routes.
 */

const MCP = "/?view=console/settings/read/config/mcp"

async function open(page: Page, path = MCP) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
  if (path === MCP) await expect(page.getByText("What is an MCP?", { exact: true })).toBeVisible()
}

test.use({ viewport: { width: 1440, height: 900 } })

test("the MCP tab sits next to the others and says what an MCP is", async ({ page }) => {
  await open(page, "/?view=console/settings/read/config/general")
  await page.getByRole("tab", { name: "MCP" }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("console/settings/read/config/mcp")
  await expect(page.getByText("What is an MCP?", { exact: true })).toBeVisible()
  await expect(page.getByText("a browser, GitHub, the services a project names")).toBeVisible()
})

test("each client gets a command or a block with this console's address", async ({ page }) => {
  await open(page)
  const snippet = page.locator('[data-card="mcp-wizard"]').getByTestId("mcp-snippet")
  await expect(snippet.first()).toContainText("claude mcp add --transport http ponos http://127.0.0.1:")
  await expect(snippet.first()).toContainText("/mcp")

  await page.getByRole("button", { name: "Claude desktop", exact: true }).click()
  await expect(page.getByText("claude_desktop_config.json", { exact: false })).toBeVisible()
  await expect(snippet.last()).toContainText('"command": "npx"')

  await page.getByRole("button", { name: "Another client", exact: true }).click()
  await expect(snippet.last()).toHaveText("ponos mcp token")
})

test("the copy button copies the command", async ({ page }) => {
  // What is written, not what a shared clipboard holds: other tests run in parallel.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async (text: string) => void ((window as unknown as { copied: string }).copied = text) },
    })
  })
  await open(page)
  // The wizard's command first: the card of the servers has a copy button too,
  // and is the first one on the page while the wizard is still arriving.
  await expect(page.getByTestId("mcp-snippet").first()).toContainText("/mcp")
  await page.getByRole("button", { name: "Copy the command" }).first().click()
  await expect(page.getByText("Copied", { exact: true })).toBeVisible()
  const copied = await page.evaluate(() => (window as unknown as { copied: string }).copied)
  expect(copied).toMatch(/^claude mcp add --transport http ponos http:\/\/127\.0\.0\.1:\d+\/mcp$/)
})

test("the test confirms a console that answers", async ({ page }) => {
  await open(page)
  await page.getByRole("button", { name: "Test the connection" }).click()
  await expect(page.getByTestId("mcp-test-result")).toHaveAttribute("data-result", "ok")
  await expect(page.getByTestId("mcp-test-result")).toContainText("a client can connect")
})

test("a failed test says the probable cause and what to do", async ({ page }) => {
  await page.route("**/api/mcp/test", (route) =>
    route.fulfill({ json: { ok: false, code: "address-mismatch", status: 401, seen: "https://other.example/mcp" } })
  )
  await open(page)
  await page.getByRole("button", { name: "Test the connection" }).click()
  const result = page.getByTestId("mcp-test-result")
  await expect(result).toHaveAttribute("data-result", "failed")
  await expect(result).toContainText("The connection failed.")
  await expect(result).toContainText("Probable cause: The console reads itself under another address")
  await expect(result).toContainText("https://other.example/mcp")
  await expect(result).toContainText("What to do: Set the “Public address”")
})

test("the servers of the sessions are listed with their state", async ({ page }) => {
  await page.route("**/api/mcp/servers", (route) =>
    route.fulfill({
      json: {
        available: true,
        failed: false,
        servers: [
          { name: "playwright", target: "npx @playwright/mcp", state: "ok" },
          { name: "github", target: "https://api.github.com/mcp", state: "auth" },
          { name: "broken", target: "npx", state: "error" },
        ],
      },
    })
  )
  await open(page)
  const list = page.getByTestId("mcp-servers")
  await expect(list.locator("[data-server]")).toHaveCount(3)
  await expect(list.locator('[data-server="playwright"]')).toHaveAttribute("data-state", "ok")
  await expect(list.locator('[data-server="playwright"]')).toContainText("Connected")
  await expect(list.locator('[data-server="github"]')).toContainText("To sign in")
  await expect(list.locator('[data-server="broken"]')).toContainText("Failing")
})
