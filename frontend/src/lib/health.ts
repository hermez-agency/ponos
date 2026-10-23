/* The installation's health, without a DOM.
 *
 * How the band over the dashboard groups what the server found wrong
 * (`GET /api/health`, from `health.py`): the shapes are the schema's, in
 * `types.ts`. Imports only types, which `node --test` strips, so it reads it
 * as it stands (see health.test.ts).
 *
 * The sentences arrive as English templates with `{{name}}` holes and the
 * params that fill them: the page hands each to `t()`, and `french.ts` holds
 * the other language. What a tool printed (`evidence`) is quoted, not translated.
 */

import type { HealthCheck, HealthGroup } from "./types.ts"

/** The groups, in the order the band lists them. */
export const HEALTH_GROUPS: readonly HealthGroup[] = ["notion", "github", "claude", "projects", "machine"]

/** The checks that are not green, errors before warnings, each group in its place. */
export function failing(checks: HealthCheck[]): HealthCheck[] {
  const rank = (check: HealthCheck) => HEALTH_GROUPS.indexOf(check.group)
  return checks
    .filter((check) => check.state !== "ok")
    .map((check, index) => ({ check, index }))
    .sort(
      (a, b) =>
        rank(a.check) - rank(b.check) ||
        Number(b.check.state === "error") - Number(a.check.state === "error") ||
        a.index - b.index
    )
    .map(({ check }) => check)
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
