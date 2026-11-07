/* The band over the dashboard, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { blocking, byGroup, failing, fixParams, quoted, shown, silent } from "./health.ts"
import type { HealthCheck } from "./types.ts"

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
  notes: [],
  fix: null,
  ...extra,
})

test("a board with nothing red draws no band", () => {
  assert.equal(shown([check("board.tickets", "ok"), check("machine.disk", "ok")]), false)
  assert.equal(shown([check("machine.update", "info"), check("settings.reply", "info")]), false, "a setting said, not a fault")
  assert.equal(shown([]), false)
  assert.equal(shown([check("machine.disk", "warn")]), true)
})

test("what fails is listed by group, errors before warnings", () => {
  const found = [
    check("machine.disk", "error"),
    check("projects.branch", "warn"),
    check("board.tickets", "error"),
    check("claude.login", "ok"),
    check("github.access", "error"),
    check("settings.secrets", "error"),
    check("settings.language", "info"),
  ]
  assert.deepEqual(
    failing(found).map((one) => one.code),
    ["board.tickets", "github.access", "projects.branch", "machine.disk", "settings.secrets"]
  )
  assert.deepEqual(
    byGroup(found).map((entry) => entry.group),
    ["board", "github", "projects", "machine", "settings"]
  )
})

test("a fix's sentences are filled with the check's params and what the fix would add", () => {
  const one = check("projects.branch", "error", {
    params: { project: "Ponos" },
    fix: { action: "project_branch", label: "Configure", confirm: "", missing: "“Runner”", target: "" },
  })
  assert.deepEqual(fixParams(one), { project: "Ponos", missing: "“Runner”" })
  assert.deepEqual(fixParams(check("machine.disk", "error", { params: { free: "1" } })), { free: "1" })
})

test("only an error that stops the runner is said to stop tickets; a channel's is a lost notification", () => {
  const slack = check("machine.notify", "error", { params: { channel: "Slack" } })
  assert.equal(blocking(slack), false, "the tickets still run")
  assert.deepEqual(silent([slack, check("machine.disk", "warn")]), ["Slack"])
  for (const code of ["board.tickets", "claude.login", "github.access", "projects.repository"]) {
    assert.equal(blocking(check(code, "error")), true, code)
  }
  assert.equal(blocking(check("board.tickets", "warn")), false)
  assert.deepEqual(silent([check("machine.notify", "ok", { params: { channel: "Telegram" } })]), [])
})

test("in French, the names a sentence quotes are quoted the French way", () => {
  const params = { options: "“Improvement” (1), “Security” (5)", count: "6", missing: "“Type”, “Sous-type”" }
  assert.deepEqual(quoted(params, true), {
    options: "« Improvement » (1), « Security » (5)",
    count: "6",
    missing: "« Type », « Sous-type »",
  })
  assert.deepEqual(quoted(params, false), params, "English keeps its own quotes")
})
