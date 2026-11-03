import { execFileSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { expect, test, type Page } from "@playwright/test"

/* A project is created from the console, in a window drawn like "New idea".
 *
 * Run against the console the deleting tests have, because every other one
 * counts its projects. What is tested is the way a person goes: the button
 * beside Cards / Table and the palette's entry, a name already taken refused
 * with the way to it, a repository the server says will be cloned, a folder
 * whose `origin` fills GitHub in, and — once created — the card first in the
 * list, marked, its "+ Ticket" ready; or the first ticket's form straight away.
 */

const LIST = "/?view=console/projects/list&variant=cards"

/* The names of this attempt's projects. A retry runs the file again on the same
 * board, where the first attempt's are already taken. */
const RUN = Date.now().toString(36).slice(-5)
const PRESS = `Press kit ${RUN}`
const SPLIT = `Split made ${RUN}`
const BRAND = `Brand assets ${RUN}`
const JOURNAL = `Journal site ${RUN}`

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(LIST)
  await expect(page.getByText("Website").first()).toBeVisible()
}

const header = (page: Page) => page.locator('[data-slot="list-header"]')
const window_ = (page: Page) => page.locator("[data-project-window]")
const create = (page: Page) => window_(page).getByRole("button", { name: "Create the project" })

async function newProject(page: Page) {
  await header(page).getByRole("link", { name: "New project", exact: true }).click()
  await expect(window_(page)).toBeVisible()
  await expect(window_(page).getByRole("heading", { name: "New project" })).toBeVisible()
}

test.describe("at 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } })
  // They create projects on one board, and the first counts them.
  test.describe.configure({ mode: "serial" })

  test("a writing project is created, first in the list and ready for a ticket", async ({ page }) => {
    await open(page)
    const counted = page.getByText(/of \d+ projects have a repository/)
    const before = Number((await counted.textContent())?.match(/of (\d+)/)?.[1])

    await newProject(page)
    await expect(create(page)).toBeDisabled()
    // A name already taken, whatever its case: refused, with the way to it.
    await page.keyboard.type("website")
    await expect(window_(page).locator('[data-slot="project-name-taken"]')).toContainText("Website")
    await expect(window_(page).getByRole("link", { name: "Open it" })).toBeVisible()
    await expect(create(page)).toBeDisabled()

    await page.getByPlaceholder("Project name").fill(PRESS)
    await page.getByPlaceholder("What the project does, in one sentence").fill("What journalists download.")
    await window_(page).getByRole("button", { name: "Writing", exact: true }).click()
    // No repository to give a writing project.
    await expect(window_(page).getByRole("button", { name: "GitHub" })).toHaveCount(0)
    await expect(window_(page)).toContainText("Without a repository, its tickets come back as a document.")
    await page.getByPlaceholder("https://").fill("https://example.com/press")
    await page.screenshot({ path: "test-results/project-new.png" })
    await page.getByPlaceholder("What the project does, in one sentence").press("Control+Enter")

    await expect(window_(page)).toBeHidden()
    await expect(page.getByText("Project created")).toBeVisible()
    const first = page.locator("[data-project-card]").first()
    await expect(first).toContainText(PRESS)
    await expect(first).toHaveAttribute("data-fresh", "true")
    await expect(first.locator("xpath=..").locator("[data-project-new-ticket]")).toBeVisible()
    await expect(counted).toContainText(`of ${before + 1} projects`)

    const listed = await (await page.request.get("/api/projects")).json()
    const made = listed.projects.find((project: { name: string }) => project.name === PRESS)
    expect(made.kind).toBe("document")
  })

  test("in the split layout the new project is in the list at once, and open in the panel", async ({ page }) => {
    await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
    await page.goto("/?view=console/projects/list")
    await expect(page.locator("[data-project-item]", { hasText: "Website" })).toBeVisible()
    await newProject(page)
    await page.getByPlaceholder("Project name").fill(SPLIT)
    await window_(page).getByRole("button", { name: "Writing", exact: true }).click()
    await page.getByPlaceholder("What the project does, in one sentence").press("Control+Enter")
    await expect(window_(page)).toBeHidden()
    const item = page.locator("[data-project-item]", { hasText: SPLIT })
    await expect(item).toHaveAttribute("data-selected", "true")
    await expect(page.locator("[data-project-panel]")).toContainText(SPLIT)
  })

  test("a code project from GitHub says it will be cloned, and goes on to its first ticket", async ({ page }) => {
    await open(page)
    await newProject(page)
    await page.getByPlaceholder("Project name").fill(BRAND)
    await expect(window_(page).getByRole("button", { name: "Code", exact: true })).toHaveAttribute("aria-pressed", "true")
    await page.getByPlaceholder("owner/repo").fill("gitlab.com/someone/assets")
    await expect(window_(page)).toContainText("is not a GitHub repository")
    await page.getByPlaceholder("owner/repo").fill("example/brand-assets")
    await expect(window_(page)).toContainText("https://github.com/example/brand-assets")
    await expect(window_(page)).toContainText("it will be at the first ticket")

    await window_(page).getByRole("checkbox", { name: "Create a first ticket" }).check()
    await create(page).click()

    // The ticket's form, over the list, with the new project already in it.
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByPlaceholder("Remove the banner from the dashboard")).toBeVisible()
    await expect(dialog).toContainText(BRAND)
    await expect(window_(page)).toHaveCount(0)

    const listed = await (await page.request.get("/api/projects")).json()
    const made = listed.projects.find((project: { name: string }) => project.name === BRAND)
    expect(made.repository).toBe("https://github.com/example/brand-assets")
  })

  test("a code project from a folder of this machine, whose origin fills GitHub in", async ({ page }) => {
    const folder = mkdtempSync(join(tmpdir(), "ponos-new-project-"))
    execFileSync("git", ["init", "-q", folder])
    execFileSync("git", ["-C", folder, "remote", "add", "origin", "git@github.com:example/journal-site.git"])

    await open(page)
    await page.keyboard.press("Control+k")
    await page.getByPlaceholder("Type a page, a project, a ticket…").fill("New project")
    await page.getByRole("option", { name: "New project" }).click()
    await expect(window_(page)).toBeVisible()

    await page.getByPlaceholder("Project name").fill(JOURNAL)
    await window_(page).getByRole("button", { name: "Local folder" }).click()
    const path = window_(page).getByPlaceholder("~/workspace/that-repository")
    await path.fill(`${folder}-nowhere`)
    await expect(window_(page)).toContainText("There is no folder at")
    await path.fill(folder)
    await expect(window_(page)).toContainText("origin is https://github.com/example/journal-site")
    await window_(page).getByRole("button", { name: "GitHub" }).click()
    await expect(page.getByPlaceholder("owner/repo")).toHaveValue("https://github.com/example/journal-site")
    await create(page).click()

    await expect(window_(page)).toBeHidden()
    const listed = await (await page.request.get("/api/projects")).json()
    const made = listed.projects.find((project: { name: string }) => project.name === JOURNAL)
    expect(made.path).toBe(folder)
    expect(made.repository).toBe("https://github.com/example/journal-site")
  })

  test("the server refuses what the page let through, under its field", async ({ page }) => {
    await open(page)
    await newProject(page)
    await page.getByPlaceholder("Project name").fill("Nowhere")
    await window_(page).getByRole("button", { name: "Local folder" }).click()
    await window_(page).getByPlaceholder("~/workspace/that-repository").fill("relative/folder")
    await create(page).click()
    await expect(window_(page).getByRole("alert")).toContainText("Write the whole path")
    await expect(window_(page)).toBeVisible()
  })
})

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test("New project is a sheet up from the bottom, its button the whole width", async ({ page }) => {
    await open(page)
    await newProject(page)
    // Against the bottom edge and the two sides, once it has come up.
    await expect
      .poll(async () => {
        const box = (await window_(page).boundingBox())!
        return [Math.round(box.x), Math.round(box.width), Math.round(box.y + box.height)]
      })
      .toEqual([0, 390, 844])
    const button = await create(page).boundingBox()
    expect(button!.width).toBeGreaterThan(330)
    expect(button!.height).toBeGreaterThanOrEqual(44)
    await page.screenshot({ path: "test-results/project-new-phone.png" })
  })
})
