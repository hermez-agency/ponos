/* What this browser may do, known before the page draws a button.
 *
 * A console is shared with accounts now (`web/accounts.py`): a reader sees,
 * a member works, an admin also changes how the console runs. The server
 * writes the role of whoever opened the page onto `<html data-role>` — as it
 * writes the language — so the resources, declared once as the bundle loads,
 * know it already: a permission read later would be a button drawn, then
 * taken back. The API refuses all the same; this is only so a reader is not
 * offered what would be refused.
 *
 * No attribute is the token, or a server from before accounts: the machine
 * itself, which may do everything.
 */

export type Role = "reader" | "member" | "admin"

const ROLES: readonly Role[] = ["reader", "member", "admin"]

export function role(): Role {
  const said = typeof document === "undefined" ? undefined : document.documentElement.dataset.role
  return ROLES.includes(said as Role) ? (said as Role) : "admin"
}

/** Writes, launches, answers, validates: a member, or an admin. */
export const canAct = () => role() !== "reader"

/** The settings, the vault, the accounts: an admin's. */
export const isAdmin = () => role() === "admin"

/* What a resource of react-resource-view is allowed when nothing may be
 * written: spread last into its `permissions`, so the package draws no "New",
 * no edit and no trash — and the board no drag, which is an `update`. */
const READS_ONLY = { create: false, update: false, delete: false } as const

export const readOnly = () => (canAct() ? {} : READS_ONLY)

/** The same, for what only an admin writes: the settings' own lists. */
export const adminOnly = () => (isAdmin() ? {} : READS_ONLY)
