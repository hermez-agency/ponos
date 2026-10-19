/* The band over the dashboard, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { byGroup, failing, fixParams, shown, type HealthCheck } from "./health.ts"

const check = (code: string, state: HealthCheck["state"], extra: Partial<HealthCheck> = {}): HealthCheck => ({
  code,
  group: code.split(".")[0] as HealthCheck["group"],
  state,
  title: code,
  said: code,
  params: {},
  cause: "",
  steps: [],
  url: "",
  evidence: "",
  fix: null,
  ...extra,
})

test("a board with nothing red draws no band", () => {
  assert.equal(shown([check("notion.token", "ok"), check("machine.disk", "ok")]), false)
  assert.equal(shown([]), false)
  assert.equal(shown([check("machine.disk", "warn")]), true)
})

test("what fails is listed by group, errors before warnings", () => {
  const found = [
    check("machine.disk", "error"),
    check("notion.statuses", "warn"),
    check("notion.columns", "error"),
    check("claude.login", "ok"),
    check("github.access", "error"),
  ]
  assert.deepEqual(
    failing(found).map((one) => one.code),
    ["notion.columns", "notion.statuses", "github.access", "machine.disk"]
  )
  assert.deepEqual(
    byGroup(found).map((entry) => entry.group),
    ["notion", "github", "machine"]
  )
})

test("a fix's sentences are filled with the check's params and what the fix would add", () => {
  const one = check("notion.columns", "error", {
    params: { project: "Ponos" },
    fix: { action: "notion_columns", label: "Configure", confirm: "", missing: "“Runner”", target: "" },
  })
  assert.deepEqual(fixParams(one), { project: "Ponos", missing: "“Runner”" })
  assert.deepEqual(fixParams(check("machine.disk", "error", { params: { free: "1" } })), { free: "1" })
})
