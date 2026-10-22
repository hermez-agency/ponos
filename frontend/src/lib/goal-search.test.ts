/* What the Goals list keeps, and how a goal's progress is counted.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { dueOf, keeps, progressOf, valuesOf } from "./goal-search.ts"

const LAUNCH = {
  status: "En cours",
  projects: ["Website", "Ponos"],
  tickets: { done: 3, running: 1, ready: 2, cancelled: 4 },
}
const TIDY = { status: "Pas commencé", projects: [], tickets: {} }

test("a goal is done tickets out of every ticket but those given up", () => {
  assert.deepEqual(progressOf(LAUNCH), { done: 3, total: 6 })
  assert.deepEqual(progressOf(TIDY), { done: 0, total: 0 })
  assert.deepEqual(progressOf({}), { done: 0, total: 0 })
})

test("the filters keep a goal by its status and by one of its projects", () => {
  assert.ok(keeps(LAUNCH, {}))
  assert.ok(keeps(LAUNCH, { status: "En cours", project: "Ponos" }))
  assert.ok(!keeps(LAUNCH, { status: "Pas commencé" }))
  assert.ok(!keeps(TIDY, { project: "Website" }))
  assert.ok(keeps(TIDY, { status: "", project: "" }), "empty is all")
})

test("the filters offer the values the goals have, once each", () => {
  assert.deepEqual(valuesOf([LAUNCH, TIDY, LAUNCH], "status"), ["En cours", "Pas commencé"])
  assert.deepEqual(valuesOf([LAUNCH, TIDY], "projects"), ["Ponos", "Website"])
})

test("a due date is said as a day, whatever time Notion gave it", () => {
  assert.equal(dueOf("2026-12-31", "en-GB"), "31 Dec 2026")
  assert.equal(dueOf("2026-12-31T18:00:00.000+02:00", "en-GB"), "31 Dec 2026")
  assert.equal(dueOf("", "en-GB"), "")
  assert.equal(dueOf("Q4", "en-GB"), "Q4")
})
