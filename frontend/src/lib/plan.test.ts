/* The plan a card draws its bar from, held to what it claims.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { advance, planOf, readPlan } from "./plan.ts"

const plan = (...tasks: [string, string][]) =>
  JSON.stringify(tasks.map(([content, status]) => ({ content, active: `${content}…`, status })))

test("the percentage is the finished tasks over the plan's, and says what is under way", () => {
  const tasks = readPlan(plan(["a", "completed"], ["b", "completed"], ["c", "in_progress"], ["d", "pending"]))
  assert.deepEqual(advance(tasks), { done: 2, total: 4, percent: 50, current: "c…" })
})

test("a task added to the plan moves the figure back", () => {
  const before = planOf([{ label: "Plan", detail: plan(["a", "completed"]) }])
  const after = planOf([
    { label: "Plan", detail: plan(["a", "completed"]) },
    { label: "Bash", detail: "ls" },
    { label: "Plan", detail: plan(["a", "completed"], ["b", "pending"]) },
  ])
  assert.equal(advance(before)?.percent, 100)
  assert.equal(advance(after)?.percent, 50)
})

test("without a plan there is no figure, never an invented one", () => {
  assert.equal(advance(planOf([{ label: "Bash", detail: "ls" }])), null)
  assert.deepEqual(readPlan("not json"), [])
  assert.deepEqual(readPlan("{}"), [])
  assert.equal(advance([]), null)
})
