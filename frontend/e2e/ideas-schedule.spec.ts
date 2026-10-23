import { expect, test, type Page } from "@playwright/test"

/* Ideas found on a schedule: the window that sets it, the line that says what
 * it will do, the project that turns itself off, and the calendar that draws it.
 *
 * One server and one file, one test after another — the schedule is the
 * console's, and each test starts from what the one before left. Nothing runs:
 * the first moment of a schedule is drawn and waited for, four hours away.
 */

test.describe.configure({ mode: "serial" })
test.use({ viewport: { width: 1440, height: 900 } })

const PAGE = "/?view=console/ideas/list"
const WEBSITE = "/?view=console/projects/read/0000000000000000000000000000cafe&tab=settings"

async function open(page: Page, path = PAGE) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(path)
}

const settings = (page: Page) => page.getByRole("button", { name: "Settings", exact: true })
const window_ = (page: Page) => page.locator('[data-slot="ideas-settings-window"]')
const line = (page: Page) => page.locator('[data-slot="ideas-plan-line"]')
const switchOf = (page: Page) => page.getByRole("switch", { name: "Find ideas for this project on the schedule" })

async function pick(page: Page, label: string, option: string) {
  await window_(page).getByRole("combobox", { name: label }).click()
  await page.getByRole("option", { name: option, exact: true }).click()
}

test("nothing is scheduled until somebody says so, and the button is still there", async ({ page }) => {
  await open(page)
  await expect(line(page)).toContainText("No automatic search")
  await expect(page.getByRole("button", { name: "Ponos, find me ideas", exact: true })).toBeVisible()
  await settings(page).click()
  await expect(window_(page).getByRole("combobox", { name: "How often" })).toContainText("Never, only when I ask")
  await expect(window_(page).getByRole("spinbutton", { name: "Ideas per project" })).toHaveValue("10")
  await expect(window_(page).getByRole("spinbutton", { name: "Skip above" })).toHaveValue("20")
})

test("every four hours for the projects ticked is saved, and said at the head of the page", async ({ page }) => {
  await open(page)
  await settings(page).click()
  await pick(page, "How often", "Every 4 hours")
  await pick(page, "Which projects", "Selected projects")
  const website = window_(page).getByRole("checkbox", { name: "Website" })
  await website.check()
  await window_(page).getByRole("spinbutton", { name: "Ideas per project" }).fill("5")
  await window_(page).getByRole("spinbutton", { name: "Budget per pass ($)" }).fill("1.5")
  await window_(page).getByRole("button", { name: "Save", exact: true }).click()
  await expect(window_(page)).toHaveCount(0)
  await expect(line(page)).toContainText("Next pass:")

  await page.reload()
  await expect(line(page)).toContainText("Next pass:")
  await settings(page).click()
  await expect(window_(page).getByRole("combobox", { name: "How often" })).toContainText("Every 4 hours")
  await expect(window_(page).getByRole("checkbox", { name: "Website" })).toBeChecked()
  await expect(window_(page).getByRole("spinbutton", { name: "Ideas per project" })).toHaveValue("5")
  await expect(window_(page).getByRole("spinbutton", { name: "Budget per pass ($)" })).toHaveValue("1.5")
})

test("a cron line that is not one is refused with the reason", async ({ page }) => {
  await open(page)
  await settings(page).click()
  await pick(page, "How often", "A cron expression")
  await window_(page).getByRole("textbox", { name: "Cron expression" }).fill("every day")
  await window_(page).getByRole("button", { name: "Save", exact: true }).click()
  await expect(window_(page)).toContainText("is not a cron line")
  await window_(page).getByRole("button", { name: "Cancel", exact: true }).click()
})

test("a project turns itself off from its own page, and the list in the window shows it", async ({ page }) => {
  await open(page, WEBSITE)
  await expect(switchOf(page)).toHaveAttribute("aria-checked", "true")
  await expect(page.getByText("Follows the general settings.")).toBeVisible()
  await switchOf(page).click()
  await expect(switchOf(page)).toHaveAttribute("aria-checked", "false")
  await expect(page.getByText("This project's own choice, whatever the general settings say.")).toBeVisible()

  await open(page)
  await settings(page).click()
  await expect(window_(page).getByRole("checkbox", { name: "Website" })).not.toBeChecked()
  await window_(page).getByRole("button", { name: "Cancel", exact: true }).click()
})

test("the scheduled pass is on the calendar of the recurrences, read only", async ({ page }) => {
  await open(page, "/?view=console/schedules/list&variant=calendar")
  const passes = page.getByRole("button", { name: /launches · Ponos finds ideas/ })
  await expect(passes.first()).toBeVisible()
  await passes.first().click()
  await expect(page.locator('[data-slot="ideas-pass-launch"]')).toContainText("Ponos looks for ideas then")
  await expect(page.locator('[data-slot="ideas-pass-launch"]').getByRole("button", { name: /Delete/ })).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Change it in the Ideas page's Settings" })).toBeVisible()
})

test("turned off again, there is no pass and the calendar loses it", async ({ page }) => {
  await open(page)
  await settings(page).click()
  await pick(page, "How often", "Never, only when I ask")
  await window_(page).getByRole("button", { name: "Save", exact: true }).click()
  await expect(window_(page)).toHaveCount(0)
  await expect(line(page)).toContainText("No automatic search")
  await open(page, "/?view=console/schedules/list&variant=calendar")
  await expect(page.getByRole("button", { name: /Ponos finds ideas/ })).toHaveCount(0)
})
