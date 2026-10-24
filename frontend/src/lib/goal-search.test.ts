/* What the Goals list keeps, in which order, and how a goal's progress is counted.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { byDeadline, deadlineOf, todayOf } from "./goal-deadline.ts"
import { EVERY_STATUS, dueOf, keeps, offeredTo, progressOf, projectFirst, valuesOf } from "./goal-search.ts"

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
  assert.ok(keeps(TIDY, { status: EVERY_STATUS, project: "" }), "all is all")
})

test("the list rests on the active goals, and keeps the closed ones for those who ask", () => {
  const met = { ...LAUNCH, status: "atteint", active: false }
  assert.ok(keeps({ ...LAUNCH, active: true }, {}))
  assert.ok(keeps(TIDY, { status: "" }), "a goal the server did not judge is active")
  assert.ok(!keeps(met, {}))
  assert.ok(!keeps(met, { status: "" }))
  assert.ok(keeps(met, { status: EVERY_STATUS }))
  assert.ok(keeps(met, { status: "atteint" }))
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

test("the list is the soonest due first, those without a date last, then the highest priority", () => {
  const goals = [
    { id: "undated", due: "", priority: 90 },
    { id: "late", due: "2026-12-31", priority: 10 },
    { id: "unscored", due: "2026-11-01", priority: null },
    { id: "soon", due: "2026-11-01T09:00:00.000+02:00", priority: 75 },
    { id: "sooner", due: "2026-10-01", priority: 0 },
    { id: "nothing", due: "" },
  ]
  assert.deepEqual(
    byDeadline(goals).map((goal) => goal.id),
    ["sooner", "soon", "unscored", "late", "undated", "nothing"]
  )
  assert.equal(goals[0].id, "undated", "the rows read are left as they came")
})

test("an active goal past its date is late, one due within a week is close", () => {
  const today = "2026-10-24"
  assert.deepEqual(deadlineOf({ due: "2026-10-23", active: true }, today), { late: true })
  assert.deepEqual(deadlineOf({ due: "2026-01-01" }, today), { late: true }, "a goal the server did not judge is active")
  assert.deepEqual(deadlineOf({ due: "2026-10-24T23:00:00.000+02:00" }, today), { late: false, days: 0 })
  assert.deepEqual(deadlineOf({ due: "2026-10-27" }, today), { late: false, days: 3 })
  assert.deepEqual(deadlineOf({ due: "2026-10-31" }, today), { late: false, days: 7 })
  assert.equal(deadlineOf({ due: "2026-11-01" }, today), null, "further off, the date is enough")
  assert.equal(deadlineOf({ due: "2026-10-01", active: false }, today), null, "met or given up, it is not late")
  assert.equal(deadlineOf({ due: "" }, today), null)
  assert.equal(deadlineOf({ due: "Q4" }, today), null)
  // Across the change of hour, a day is still a day.
  assert.deepEqual(deadlineOf({ due: "2026-10-26" }, "2026-10-24"), { late: false, days: 2 })
})

test("today is the reader's day, written as a due date is", () => {
  assert.equal(todayOf(new Date(2026, 0, 5, 23, 30)), "2026-01-05")
})

test("a ticket is offered the goals the board offers, its project's first, and the one it serves", () => {
  const choices = [
    { value: "tidy", label: "Ranger", projects: [] },
    { value: "launch", label: "Lancer", projects: ["site"] },
    { value: "elsewhere", label: "Ailleurs", projects: ["other"] },
  ]
  const ids = (offered: { id: string }[]) => offered.map((goal) => goal.id)
  assert.deepEqual(ids(offeredTo(choices, "")), ["tidy", "launch", "elsewhere"])
  assert.deepEqual(ids(offeredTo(choices, "site")), ["launch", "tidy", "elsewhere"])
  assert.deepEqual(ids(offeredTo(choices, "site", { id: "launch", name: "Lancer" })), ["launch", "tidy", "elsewhere"])
  // Over, the board no longer offers it, and it is still the one the ticket serves: drawn, not taken for none.
  const met = offeredTo(choices, "site", { id: "met", name: "Livrer la bêta" })
  assert.deepEqual(ids(met), ["met", "launch", "tidy", "elsewhere"])
  assert.equal(met[0].name, "Livrer la bêta")
  assert.deepEqual(offeredTo([], ""), [])
})

test("the project's come first, the rest in the order they came", () => {
  const choices = [
    { value: "", projects: [] },
    { value: "a", projects: ["other"] },
    { value: "b", projects: ["site"] },
  ]
  const order = (project: string) => projectFirst(choices, project, (choice) => choice.projects).map((one) => one.value)
  assert.deepEqual(order(""), ["", "a", "b"])
  assert.deepEqual(order("site"), ["b", "", "a"])
})
