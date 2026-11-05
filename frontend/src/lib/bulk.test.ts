/* The board's selection, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { asideable, cancellable, columnState, costOf, launchable, rangeOf } from "./bulk.ts"

const card = (column: string, extra: object = {}) => ({ id: column, column, ...extra })

test("drafts, failed runs and tickets set aside by hand are launched; a question waits for its answer", () => {
  assert.equal(launchable(card("draft")), true)
  assert.equal(launchable(card("failed")), true)
  assert.equal(launchable(card("blocked")), true)
  assert.equal(launchable(card("blocked", { block: { code: "question" } })), false)
  for (const column of ["ready", "running", "paused", "review", "validated", "done", "cancelled"])
    assert.equal(launchable(card(column)), false, column)
})

test("only Ready is set aside, and nothing in the runner's hands is given up", () => {
  assert.equal(asideable(card("ready")), true)
  assert.equal(asideable(card("draft")), false)
  assert.equal(cancellable(card("draft")), true)
  assert.equal(cancellable(card("review")), true)
  for (const column of ["running", "paused", "cancelled"]) assert.equal(cancellable(card(column)), false, column)
})

test("the cost adds up the estimates there are, and counts apart the tickets without one", () => {
  const said = costOf([
    card("draft", { estimate: { cost: 1.5, cost_high: 3 } }),
    card("draft", { estimate: { cost: 0.5, cost_high: 1 } }),
    card("draft", { estimate: null }),
    card("draft"),
  ])
  assert.deepEqual(said, { cost: 2, high: 4, estimated: 2, unknown: 2 })
  assert.deepEqual(costOf([]), { cost: 0, high: 0, estimated: 0, unknown: 0 })
})

test("Shift selects every card between the last one clicked and this one, either way", () => {
  const order = ["a", "b", "c", "d", "e"]
  assert.deepEqual(rangeOf(order, "b", "d"), ["b", "c", "d"])
  assert.deepEqual(rangeOf(order, "d", "b"), ["b", "c", "d"])
  assert.deepEqual(rangeOf(order, "c", "c"), ["c"])
  assert.deepEqual(rangeOf(order, null, "c"), ["c"], "no card clicked before")
  assert.deepEqual(rangeOf(order, "z", "c"), ["c"], "the first one left the column")
})

test("a column's box is ticked when all its cards are, half when some are", () => {
  assert.equal(columnState(["a", "b"], new Set()), false)
  assert.equal(columnState(["a", "b"], new Set(["a"])), "indeterminate")
  assert.equal(columnState(["a", "b"], new Set(["a", "b", "z"])), true)
  assert.equal(columnState([], new Set(["a"])), false)
})
