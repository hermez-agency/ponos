/* The order the projects are listed in, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { directionOf, ordered, ordering, sortOf } from "./project-sort.ts"

const project = (name: string, created = "", count = 0, running = 0) => ({ name, created, count, running })
const OLD = project("Old", "2026-09-01T10:00:00+02:00", 40, 0)
const NEW = project("New", "2026-11-01T10:00:00+01:00", 3, 2)
const MID = project("mid", "2026-10-01T10:00:00+02:00", 12, 1)
const EMPTY_B = project("beta")
const EMPTY_A = project("Alpha")
const all = [EMPTY_B, OLD, MID, EMPTY_A, NEW]
const names = (order: object) => ordered(all, order).map((one) => one.name)

test("by default the latest ticket created comes first, projects without a ticket last, by name", () => {
  assert.deepEqual(names({}), ["New", "mid", "Old", "Alpha", "beta"])
  assert.equal(sortOf({}), "created")
  assert.equal(ordering({}), false)
})

test("dates are compared as instants, not as text", () => {
  const late = project("late", "2026-11-01T00:30:00+02:00")
  const early = project("early", "2026-10-31T23:45:00+00:00")
  assert.deepEqual(ordered([early, late]).map((one) => one.name), ["early", "late"])
})

test("projects without a ticket stay last in either direction", () => {
  assert.deepEqual(names({ sort: "created", dir: "asc" }), ["Old", "mid", "New", "Alpha", "beta"])
  assert.deepEqual(names({ sort: "count", dir: "asc" }), ["New", "mid", "Old", "Alpha", "beta"])
})

test("by name goes upwards, and downwards on request", () => {
  assert.deepEqual(names({ sort: "name" }), ["Alpha", "beta", "mid", "New", "Old"])
  assert.deepEqual(names({ sort: "name", dir: "desc" }), ["Old", "New", "mid", "beta", "Alpha"])
})

test("by number of tickets and by tickets running", () => {
  assert.deepEqual(names({ sort: "count" }), ["Old", "mid", "New", "Alpha", "beta"])
  assert.deepEqual(names({ sort: "running" }), ["New", "mid", "Old", "Alpha", "beta"])
})

test("an unknown sort or direction falls back to the default", () => {
  assert.equal(sortOf({ sort: "nope" }), "created")
  assert.equal(directionOf({ sort: "name", dir: "up" }), "asc")
  assert.equal(ordering({ sort: "name" }), true)
  assert.equal(ordering({ dir: "asc" }), true)
})
