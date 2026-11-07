import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { crc32 } from "node:zlib"
import { expect, test, type Page } from "@playwright/test"

/* The Context page's Skills tab: the Claude Code skills Ponos gives its sessions.
 *
 * What is tested is the way a person goes: a skill is created for one project
 * with the Markdown editor, a skill the repository already holds is flagged and
 * the repository's own is listed read only, a skill is switched off and on,
 * edited with a file beside it, imported from a folder and from a .zip, and
 * deleted. Newsletter's clone holds one skill, `revue` (`e2e/console.py`). Another test renames
 * Newsletter, so the project is read back by its id rather than named here.
 */

const NEWSLETTER = "0000000000000000000000000000beef"
const SKILLS = "/?view=console/context/read/context/skills"

async function open(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(SKILLS)
  await expect(page.locator('[data-slot="skills-page"]')).toBeVisible()
}

/** What the console calls the project that has a clone, today. */
const newsletter = async (page: Page): Promise<string> => {
  const listed = await (await page.request.get("/api/projects")).json()
  return listed.projects.find((project: { id: string }) => project.id === NEWSLETTER).name
}
const rows = (page: Page) => page.locator('[data-slot="skill-row"]')
const row = (page: Page, name: string) => rows(page).filter({ has: page.getByText(name, { exact: true }) })
const editor = (page: Page) => page.locator('[data-slot="skill-editor"]')

const SKILL_MD = (name: string) => `---\nname: ${name}\ndescription: Imported ${name}.\n---\n\n# ${name}\n`

/** A .zip with its files stored, not compressed: enough for the importer, and no library. */
function zip(files: Record<string, string>): Buffer {
  const parts: Buffer[] = []
  const central: Buffer[] = []
  let offset = 0
  for (const [name, text] of Object.entries(files)) {
    const data = Buffer.from(text)
    const label = Buffer.from(name)
    const head = Buffer.alloc(30)
    head.writeUInt32LE(0x04034b50, 0)
    head.writeUInt16LE(20, 4)
    head.writeUInt32LE(crc32(data), 14)
    head.writeUInt32LE(data.length, 18)
    head.writeUInt32LE(data.length, 22)
    head.writeUInt16LE(label.length, 26)
    const entry = Buffer.alloc(46)
    entry.writeUInt32LE(0x02014b50, 0)
    entry.writeUInt16LE(20, 4)
    entry.writeUInt16LE(20, 6)
    entry.writeUInt32LE(crc32(data), 16)
    entry.writeUInt32LE(data.length, 20)
    entry.writeUInt32LE(data.length, 24)
    entry.writeUInt16LE(label.length, 28)
    entry.writeUInt32LE(offset, 42)
    parts.push(head, label, data)
    central.push(entry, label)
    offset += head.length + label.length + data.length
  }
  const directory = Buffer.concat(central)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0)
  end.writeUInt16LE(central.length / 2, 8)
  end.writeUInt16LE(central.length / 2, 10)
  end.writeUInt32LE(directory.length, 12)
  end.writeUInt32LE(offset, 16)
  return Buffer.concat([...parts, directory, end])
}

// One set of skills for the whole console: the tests that write it do not run side by side.
test.describe.configure({ mode: "serial" })
test.use({ viewport: { width: 1440, height: 900 } })

test("the tab sits beside the others, and the repository's skills are listed read only", async ({ page }) => {
  await open(page)
  await expect(page.getByRole("tab", { name: "Skills", exact: true })).toBeVisible()
  const held = page.locator('[data-slot="repository-skill"]')
  await expect(held).toHaveCount(1)
  await expect(held).toContainText("revue")
  await expect(held).toContainText(await newsletter(page))
  await expect(held.getByRole("button")).toHaveCount(0)
})

test("a skill is created for one project, and is in the API with its scope", async ({ page }) => {
  await open(page)
  await page.getByRole("button", { name: "New skill" }).click()
  await editor(page).getByLabel("Skill name").fill("relecture")
  await editor(page).getByLabel("What it is for", { exact: true }).fill("Reads a text before it goes out.")
  await editor(page).locator(".ProseMirror").click()
  await page.keyboard.type("Check the spelling.")
  await expect(editor(page).locator(".ProseMirror")).toContainText("Check the spelling.")
  // The editor reports its Markdown a moment after the last key; nothing on the page says when.
  await page.waitForTimeout(600)
  await editor(page).getByLabel("Scope").selectOption("some")
  await editor(page).getByRole("checkbox", { name: await newsletter(page) }).click()
  await editor(page).getByRole("button", { name: "Save", exact: true }).click()

  const made = row(page, "relecture")
  await expect(made).toBeVisible()
  await expect(made).toContainText(await newsletter(page))
  await expect(made).toContainText("Active")
  await expect(made.locator('[data-slot="skill-conflict"]')).toHaveCount(0)

  const listed = await (await page.request.get("/api/skills")).json()
  const skill = listed.skills.find((item: { name: string }) => item.name === "relecture")
  expect(skill.scope).toHaveLength(1)
  const opened = await (await page.request.get(`/api/skills/${skill.id}`)).json()
  expect(opened.markdown).toContain("name: relecture")
  expect(opened.body).toContain("Check the spelling.")
})

test("a skill the repository already holds is flagged: the repository's wins", async ({ page }) => {
  await open(page)
  await page.getByRole("button", { name: "New skill" }).click()
  await editor(page).getByLabel("Skill name").fill("revue")
  await editor(page).getByLabel("What it is for", { exact: true }).fill("Ponos's own review.")
  await editor(page).getByRole("button", { name: "Save", exact: true }).click()
  const clash = row(page, "revue").locator('[data-slot="skill-conflict"]')
  await expect(clash).toContainText(await newsletter(page))
  await expect(clash).toContainText("the repository's wins")
})

test("a skill is switched off and on, edited with a file beside it, and deleted", async ({ page }) => {
  await open(page)
  const made = row(page, "relecture")
  await made.getByRole("button", { name: "Disable" }).click()
  await expect(made).toContainText("Inactive")
  await expect(made).toHaveAttribute("data-enabled", "false")
  await made.getByRole("button", { name: "Enable" }).click()
  await expect(made).toContainText("Active")

  await made.getByRole("button", { name: "Edit" }).click()
  await editor(page).getByLabel("What it is for", { exact: true }).fill("Reads a text twice.")
  await editor(page).getByLabel("Attach files").setInputFiles({
    name: "rules.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Rules\n"),
  })
  await expect(editor(page).locator('[data-slot="skill-files"]')).toContainText("rules.md")
  await editor(page).getByRole("button", { name: "Save", exact: true }).click()
  await expect(row(page, "relecture")).toContainText("Reads a text twice.")
  await expect(row(page, "relecture")).toContainText("1 file(s)")

  await row(page, "relecture").getByRole("button", { name: "Delete" }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: /^Delete/ }).click()
  await expect(page.getByText("Skill deleted")).toBeVisible()
  await expect(row(page, "relecture")).toHaveCount(0)
})

test("a skill is imported from a folder and from a .zip", async ({ page }) => {
  await open(page)
  const folder = mkdtempSync(join(tmpdir(), "ponos-skill-"))
  const inside = join(folder, "from-folder")
  mkdirSync(join(inside, "scripts"), { recursive: true })
  writeFileSync(join(inside, "SKILL.md"), SKILL_MD("from-folder"))
  writeFileSync(join(inside, "scripts", "run.sh"), "echo hi\n")
  await page.locator('[data-slot="skill-import-folder"]').setInputFiles(inside)
  await expect(row(page, "from-folder")).toContainText("1 file(s)")

  await page.locator('[data-slot="skill-import-zip"]').setInputFiles({
    name: "from-zip.zip",
    mimeType: "application/zip",
    buffer: zip({ "from-zip/SKILL.md": SKILL_MD("from-zip"), "from-zip/notes.txt": "n" }),
  })
  await expect(row(page, "from-zip")).toContainText("1 file(s)")
  await expect(row(page, "from-zip")).toContainText("All the sessions")
})
