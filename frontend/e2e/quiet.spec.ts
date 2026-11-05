import { expect, test, type ConsoleMessage } from "@playwright/test"

/* Every page of the menu opens without a word in the browser's console.
 *
 * Sessions said "Fetch Error: the sessions are managed from their page" on
 * every opening: the package asked the resource for its list, as it asks every
 * list, and the resource threw. The page was drawn all the same, so only the
 * console showed it — and a warning nobody reads hides the next one that
 * matters. So each page is opened here, drawn to the end, and any error or
 * warning it logged on the way fails the test.
 */

/* A page and the heading it is drawn to: the Dashboard's is its board. */
const PAGES: [string, string][] = [
  ["Board", "/?view=console/tickets/list"],
  ["Projects", "/?view=console/projects/list"],
  ["Schedules", "/?view=console/schedules/list"],
  ["Ideas", "/?view=console/ideas/list"],
  ["Goals", "/?view=console/goals/list"],
  ["Conversations", "/?view=console/sessions/list"],
  ["Settings", "/?view=console/settings/read/config"],
]

for (const [name, path] of PAGES) {
  test(`${name} opens without an error or a warning in the console`, async ({ page }) => {
    const heard: string[] = []
    const listen = (message: ConsoleMessage) => {
      if (message.type() === "error" || message.type() === "warning") heard.push(`${message.type()}: ${message.text()}`)
    }
    page.on("console", listen)
    page.on("pageerror", (error) => heard.push(`pageerror: ${error.message}`))
    await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])

    await page.goto(path)
    await expect(page.getByRole("heading", { name, exact: true }).first()).toBeVisible()
    // What a page asks for once drawn — its list, the stream — has answered.
    await page.waitForLoadState("networkidle")

    expect(heard).toEqual([])
  })
}
