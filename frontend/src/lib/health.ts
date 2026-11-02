/* The installation's health, without a DOM.
 *
 * How the band over the dashboard groups what the server found wrong
 * (`GET /api/health`, from `health.py`): the shapes are the schema's, in
 * `types.ts`. Imports only types, which `node --test` strips, so it reads it
 * as it stands (see health.test.ts).
 *
 * The sentences arrive as English templates with `{{name}}` holes and the
 * params that fill them: the page hands each to `t()`, and `health-french.ts`
 * holds the other language, fetched when the band is drawn. What a tool printed (`evidence`) is quoted, not translated.
 *
 * `info` is a setting said rather than judged — what `ponos doctor` prints in
 * grey. The band lists what is to be fixed, so it leaves it out with the greens.
 *
 * Not every error stops a ticket: a messaging channel that does not answer
 * (`machine.notify`) leaves the runner taking tickets, only its notifications
 * are lost. The band says so, in amber, rather than "before tickets can run" in
 * red — a red band over tickets that run is a band one learns to ignore.
 */

import type { HealthCheck, HealthGroup } from "./types.ts"

/** The groups, in the order the band lists them. */
export const HEALTH_GROUPS: readonly HealthGroup[] = ["notion", "github", "claude", "projects", "machine", "settings"]

/** The checks that are not green, errors before warnings, each group in its place. */
export function failing(checks: HealthCheck[]): HealthCheck[] {
  const rank = (check: HealthCheck) => HEALTH_GROUPS.indexOf(check.group)
  return checks
    .filter((check) => check.state === "warn" || check.state === "error")
    .map((check, index) => ({ check, index }))
    .sort(
      (a, b) =>
        rank(a.check) - rank(b.check) ||
        Number(b.check.state === "error") - Number(a.check.state === "error") ||
        a.index - b.index
    )
    .map(({ check }) => check)
}

/** The checks that report a channel the notifications go through. */
const CHANNEL = "machine.notify"

/** Whether a check stops the runner from taking tickets: an error, but not a channel's. */
export function blocking(check: HealthCheck): boolean {
  return check.state === "error" && check.code !== CHANNEL
}

/** The channels whose notifications do not arrive — "Slack" — each named once. */
export function silent(checks: HealthCheck[]): string[] {
  const named = checks.filter((check) => check.state === "error" && check.code === CHANNEL)
  return [...new Set(named.map((check) => check.params.channel ?? ""))]
}

/** Whether the band is drawn at all: nothing, while everything is green. */
export function shown(checks: HealthCheck[]): boolean {
  return failing(checks).length > 0
}

/** The failing checks by group, in the groups' order. */
export function byGroup(checks: HealthCheck[]): { group: HealthGroup; checks: HealthCheck[] }[] {
  const left = failing(checks)
  return HEALTH_GROUPS.map((group) => ({ group, checks: left.filter((check) => check.group === group) })).filter(
    (entry) => entry.checks.length > 0
  )
}

/** The params a fix's sentences are filled with: the check's own, then the fix's. */
export function fixParams(check: HealthCheck): Record<string, string> {
  return check.fix ? { ...check.params, missing: check.fix.missing } : check.params
}
