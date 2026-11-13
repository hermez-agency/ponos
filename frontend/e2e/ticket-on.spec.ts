import { expect, test } from "@playwright/test"

/* The « On » prompt, where it can be found: a field of the creation dialog,
 * and a section of the ticket's first tab — written, changed, emptied.
 *
 * The writes are caught on their way out rather than made, so the board the
 * other tests read keeps the tickets it was made with.
 */

const ASKING = "/?view=console/tickets/read/00000000000000000000000000000a5c"

test.use({ viewport: { width: 1440, height: 900 } })

test("a new ticket is created with an On prompt", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/tickets", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: "0000000000000000000000000000f00d", title: "Chain it" } })
  })
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto("/")
  await page.getByRole("link", { name: /New ticket|Nouveau ticket/ }).first().click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText(/A prompt Ponos runs at every change/)).toBeVisible()
  await dialog.locator('[data-slot="on-input"] textarea').fill("When it is done, create the deployment ticket.")
  await dialog.getByLabel("Title").fill("Chain it")
  await dialog.getByLabel("Title").press("Control+Enter")
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toMatchObject({ title: "Chain it", on: "When it is done, create the deployment ticket." })
})

test("the On prompt of a ticket is written, found again and emptied from its first tab", async ({ page }) => {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: test.info().project.use.baseURL }])
  await page.goto(ASKING)
  await page.getByRole("tab", { name: /^(Mission|Result)/ }).click()
  const section = page.locator('[data-slot="ticket-on"]')
  await expect(section.getByText("Automation", { exact: true })).toBeVisible()
  const box = section.getByRole("textbox", { name: "Prompt on status change" })
  await box.fill("If it goes to done, create the follow-up.")
  await section.getByRole("button", { name: "Save the prompt" }).click()
  await expect(page.getByText("Prompt saved")).toBeVisible()

  // Found again, from the server, on a fresh load of the page — with its badge.
  await page.reload()
  await expect(page.locator('[data-slot="ticket-on-badge"]')).toBeVisible()
  await page.getByRole("tab", { name: /^(Mission|Result)/ }).click()
  await expect(box).toHaveValue("If it goes to done, create the follow-up.")

  // Emptied: the prompt is removed, and the badge with it.
  await box.fill("")
  await section.getByRole("button", { name: "Save the prompt" }).click()
  await expect(page.getByText("Prompt removed")).toBeVisible()
  await page.reload()
  await expect(page.locator('[data-slot="ticket-on-badge"]')).toHaveCount(0)
  await page.getByRole("tab", { name: /^(Mission|Result)/ }).click()
  await expect(box).toHaveValue("")
})
