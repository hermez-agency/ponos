/* The installation's health, without a DOM.
 *
 * What the server found wrong (`GET /api/health`, from `health.py`) and how the
 * band over the dashboard groups it. Imports nothing, so `node --test` reads it
 * as it stands (see health.test.ts).
 *
 * The sentences arrive as English templates with `{{name}}` holes and the
 * params that fill them: the page hands each to `t()`, and `french.ts` holds
 * the other language. What a tool printed (`evidence`) is quoted, not translated.
 */

export type HealthState = "ok" | "warn" | "error"

/** The groups, in the order the band lists them. */
export const HEALTH_GROUPS = ["notion", "github", "claude", "projects", "machine"] as const
export type HealthGroup = (typeof HEALTH_GROUPS)[number]

/** A fix Ponos can make itself — always asked for before it is made. */
export interface HealthFix {
  action: string
  label: string
  confirm: string
  missing: string
  target: string
}

export interface HealthCheck {
  code: string
  group: HealthGroup
  state: HealthState
  title: string
  said: string
  params: Record<string, string>
  cause: string
  steps: string[]
  url: string
  evidence: string
  /** What each name in a list is worth: “Agent” and the sentences about it. */
  notes: { name: string; said: string[] }[]
  fix: HealthFix | null
}

export interface HealthReport {
  checks: HealthCheck[]
  problems: number
  checked_at: string
  /** What a fix just did, when the report answers one. */
  done?: string
}

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
