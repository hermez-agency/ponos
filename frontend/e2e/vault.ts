import { expect, type Page } from "@playwright/test"

/* The vault page, open. The e2e console is opened with its token, and every
 * browser holding it shares one unlocked vault: a test finds it locked or not,
 * depending on which ran before — so it unlocks it when it has to. */
export async function unlocked(page: Page) {
  const locked = page.locator('[data-card="vault-locked"]')
  const open = page.locator('[data-card="vault-new"]')
  await expect(locked.or(open)).toBeVisible()
  if (await locked.isVisible()) {
    await locked.locator('[data-slot="vault-unlock-password"]').fill("e2e")
    await locked.locator('[data-slot="vault-unlock"]').click()
  }
  await expect(open).toBeVisible()
}
