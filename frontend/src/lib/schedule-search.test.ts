/* What a search over the schedules keeps, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { filtering, keeps } from "./schedule-search.ts"

const DIGEST = { name: "Weekly digest", active: true, project_id: "p1", project: "Leadz", rule: "Chaque lundi à 09:00" }
const EMAIL = { name: "Test email", active: false, project_id: "p2", project: "Opoil", rule: "Chaque heure à :00" }
const names = (filter: object) => [DIGEST, EMAIL].filter((s) => keeps(s, filter)).map((s) => s.name)

test("nothing asked keeps every schedule", () => {
  assert.deepEqual(names({}), ["Weekly digest", "Test email"])
  assert.deepEqual(names({ q: "  ", project: "", state: "" }), ["Weekly digest", "Test email"])
  assert.equal(filtering({ q: " ", project: "", state: "" }), false)
})

test("the words are looked for in the name, the project and the rule, whatever the accents", () => {
  assert.deepEqual(names({ q: "DIGEST" }), ["Weekly digest"])
  assert.deepEqual(names({ q: "opoil" }), ["Test email"])
  assert.deepEqual(names({ q: "lundi" }), ["Weekly digest"])
  assert.deepEqual(names({ q: "chaque a" }), ["Weekly digest", "Test email"])
  assert.deepEqual(names({ q: "nope" }), [])
})

test("the project keeps the schedules pointed at its page", () => {
  assert.deepEqual(names({ project: "p1" }), ["Weekly digest"])
  assert.deepEqual(names({ project: "p3" }), [])
  assert.equal(filtering({ project: "p1" }), true)
})

test("the state keeps the ones on, or the paused ones", () => {
  assert.deepEqual(names({ state: "on" }), ["Weekly digest"])
  assert.deepEqual(names({ state: "paused" }), ["Test email"])
  assert.deepEqual(names({ state: "paused", q: "digest" }), [])
  assert.equal(filtering({ state: "on" }), true)
})
