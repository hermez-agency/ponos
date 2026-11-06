import { DatabaseSync } from "node:sqlite"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { expect, test, type Browser, type Page } from "@playwright/test"

/* Two people on one console: a reader, and a member.
 *
 * `e2e/console.py accounts` serves a board of its own — two tickets in review
 * and a draft — in a directory named after its port, so that what a member
 * leaves on a ticket can be read where the board keeps it. The token is the
 * admin here: it draws the invitations, from the Accounts tab of the settings
 * as a person would, and each person takes theirs in a browser of their own.
 *
 * The accounts stay on the server once made, so each test invites people of
 * its own, under addresses no other run has used.
 */

const VALIDATED = "000000000000000000000000acc0de01"
const LOOKED_AT = "000000000000000000000000acc0de02"
const DRAFT = "000000000000000000000000acc0de03"
const ACCOUNTS = "/?view=console/settings/read/config/accounts"
const page_of = (id: string) => `/?view=console/tickets/read/${id}`

const base = () => String(test.info().project.use.baseURL)

/** The admin: the token, in the cookie the address would have left. */
async function asAdmin(page: Page) {
  await page.context().addCookies([{ name: "ponos_token", value: "e2e", url: base() }])
}

/** A link drawn from the Accounts tab, for `role`. */
async function draw(page: Page, role: "Reader" | "Member"): Promise<string> {
  await page.goto(ACCOUNTS)
  const card = page.locator('[data-card="invite"]')
  await card.locator('[data-slot="account-role"]').click()
  await page.getByRole("option", { name: role, exact: true }).click()
  await card.locator('[data-slot="invite-draw"]').click()
  const link = card.locator('[data-slot="invite-link"]')
  await expect(link).toContainText("/invite?code=")
  return (await link.textContent()) ?? ""
}

/** Somebody taking a link, in a browser of their own: signed in once the form is sent. */
async function join_(browser: Browser, link: string, name: string, email: string): Promise<Page> {
  const context = await browser.newContext({ baseURL: base() })
  const page = await context.newPage()
  await page.goto(link)
  await page.getByLabel(/^Name$/).fill(name)
  await page.getByLabel(/^Email$/).fill(email)
  await page.getByLabel(/^Password$/).fill("long enough for this")
  await page.getByRole("button", { name: "Create my account" }).click()
  await page.waitForURL((url) => !url.pathname.startsWith("/invite"))
  return page
}

const unique = (who: string) => `${who}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.com`

test.use({ viewport: { width: 1440, height: 900 } })

test("a reader sees the board and the tickets, is offered nothing to change them, and is refused by the API", async ({
  page,
  browser,
}) => {
  await asAdmin(page)
  const reader = await join_(browser, await draw(page, "Reader"), "Tom", unique("tom"))

  await reader.goto("/")
  await expect(reader.locator(`[data-ticket-card="${DRAFT}"]`)).toBeVisible()
  await expect(reader.locator(`[data-ticket-card="${LOOKED_AT}"]`)).toBeVisible()
  // Nothing to write, launch, pick, move or talk with.
  await expect(reader.getByRole("link", { name: /New ticket|Nouveau ticket/ })).toHaveCount(0)
  await expect(reader.locator('[data-slot="card-select"]')).toHaveCount(0)
  await expect(reader.locator('[data-slot="column-select"]')).toHaveCount(0)
  await expect(reader.locator(`[data-decide="${LOOKED_AT}"]`)).toHaveCount(0)
  await expect(reader.getByRole("button", { name: /^Open the console/ })).toHaveCount(0)
  await expect(reader.locator('[data-ticket-card] [data-slot="block-action"]')).toHaveCount(0)

  // On a ticket in review: what it brought back, and no way to decide on it.
  await reader.goto(page_of(LOOKED_AT))
  await expect(reader.getByRole("heading", { name: "A ticket a reader looks at" })).toBeVisible()
  await expect(reader.locator('[data-slot="ticket-decide-tab"]')).toHaveCount(0)
  await expect(reader.locator('[data-slot="ticket-decide-cue"]')).toHaveCount(0)
  await reader.locator('[data-slot="ticket-talk-tab"]').click()
  await expect(reader.getByText("Adds a share button under each article.")).toBeVisible()
  await expect(reader.locator('[data-slot="composer"]')).toHaveCount(0)

  // Neither are the settings in its menu.
  await expect(reader.getByRole("link", { name: "Settings", exact: true })).toHaveCount(0)

  // And the API says no all the same, whatever the page would have offered.
  for (const [path, data] of [
    [`/api/tickets/${DRAFT}/status`, { column: "ready" }],
    [`/api/tickets/${LOOKED_AT}/decision`, { key: "validate" }],
    [`/api/tickets/${LOOKED_AT}/talk`, { text: "hello" }],
    ["/api/tickets", { title: "Mine" }],
    ["/api/settings", {}],
  ] as const) {
    const refused = await reader.request.post(path, { data, headers: { "X-Ponos": "1" } })
    expect(refused.status(), path).toBe(403)
  }
  expect((await reader.request.get("/api/accounts")).status()).toBe(403)
  const me = await (await reader.request.get("/api/me")).json()
  expect(me).toMatchObject({ name: "Tom", role: "reader" })
  await reader.context().close()
})

test("a member validates a ticket in review, and the comment on it says who", async ({ page, browser }) => {
  await asAdmin(page)
  // Back in review, should a run before this one have validated it.
  const back = await page.request.post(`/api/tickets/${VALIDATED}/status`, {
    data: { column: "review" },
    headers: { "X-Ponos": "1" },
  })
  expect(back.ok()).toBe(true)
  await expect
    .poll(async () => {
      const board = await (await page.request.get("/api/board")).json()
      return board.tickets.find((ticket: { id: string }) => ticket.id === VALIDATED)?.column
    })
    .toBe("review")

  const member = await join_(browser, await draw(page, "Member"), "Léa", unique("lea"))
  // The admin's list says who joined, and as what.
  await page.goto(ACCOUNTS)
  await expect(page.locator('[data-account] >> text="Léa"').first()).toBeVisible()

  // Not the settings: those are an admin's.
  expect((await member.request.post("/api/settings", { data: {}, headers: { "X-Ponos": "1" } })).status()).toBe(403)
  // Nor the vault, not even its list.
  expect((await member.request.get("/api/vault")).status()).toBe(403)
  expect((await member.request.post("/api/vault", { data: { name: "X_TOKEN" }, headers: { "X-Ponos": "1" } })).status()).toBe(403)

  await member.goto(page_of(VALIDATED))
  await member.locator('[data-slot="ticket-decide-tab"]').click()
  await member
    .locator('[data-slot="ticket-decision"]')
    .getByRole("button", { name: "Validate", exact: true })
    .click()
  await expect
    .poll(async () => {
      const board = await (await member.request.get("/api/board")).json()
      return board.tickets.find((ticket: { id: string }) => ticket.id === VALIDATED)?.column
    })
    .toBe("validated")

  // What the board keeps: the line that says where the answer came from names her.
  const port = new URL(base()).port
  const database = new DatabaseSync(join(tmpdir(), `ponos-e2e-accounts-${port}`, "state", "ponos", "ponos.db"), { readOnly: true })
  const kept = (database.prepare("SELECT text FROM ticket_comments WHERE ticket = ? ORDER BY id").all(VALIDATED) as { text: string }[])
    .map((row) => row.text)
    .join("\n")
  database.close()
  expect(kept).toContain("Answered from the console by Léa.")
  expect(kept).toContain("Decision: validated.")

  // And the ticket's own history, from the console, says it too.
  await member.goto(page_of(VALIDATED))
  const audit = member.locator('[data-slot="ticket-audit"]')
  await expect(audit).toContainText("Léa")
  await expect(audit).toContainText("validated it")
  await member.context().close()
})
