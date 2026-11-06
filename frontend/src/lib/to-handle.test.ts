/* What waits for you on a phone, held to the order it is shown in and to the column the board opens on.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { openingColumn, rankOf, toHandle, type Waiting } from "./to-handle.ts"

const ticket = (id: string, column: string, edited: string, policy = "ask"): Waiting => ({
  id,
  column,
  edited,
  block: column === "blocked" ? { policy } : null,
})

test("only the blocked tickets and the ones in review are to handle", () => {
  const tickets = [
    ticket("draft", "draft", "2026-11-01T10:00:00Z"),
    ticket("running", "running", "2026-11-01T10:00:00Z"),
    ticket("review", "review", "2026-11-01T10:00:00Z"),
    ticket("blocked", "blocked", "2026-11-01T10:00:00Z"),
    ticket("done", "done", "2026-11-01T10:00:00Z"),
  ]
  assert.deepEqual(
    toHandle(tickets).map((one) => one.id),
    ["blocked", "review"]
  )
  assert.equal(rankOf(tickets[0]), -1)
})

test("a blocked ticket comes before a review, and a stop Ponos is on comes last", () => {
  const tickets = [
    ticket("retries", "blocked", "2026-10-01T10:00:00Z", "retry:2"),
    ticket("waits-base", "blocked", "2026-10-02T10:00:00Z", "wait-base"),
    ticket("review", "review", "2026-10-03T10:00:00Z"),
    ticket("asks", "blocked", "2026-11-05T10:00:00Z"),
  ]
  assert.deepEqual(
    toHandle(tickets).map((one) => one.id),
    ["asks", "review", "retries", "waits-base"]
  )
})

test("inside a group, the one waiting longest comes first", () => {
  const tickets = [
    ticket("new", "blocked", "2026-11-05T10:00:00Z"),
    ticket("old", "blocked", "2026-10-26T10:00:00Z"),
    ticket("middle", "blocked", "2026-11-01T10:00:00Z"),
  ]
  assert.deepEqual(
    toHandle(tickets).map((one) => one.id),
    ["old", "middle", "new"]
  )
})

test("the board opens on the column chosen last, else on what waits for you", () => {
  const columns = ["draft", "ready", "running", "blocked", "review", "done"]
  assert.equal(openingColumn(columns, new Set(["draft", "blocked", "review"])), "blocked")
  assert.equal(openingColumn(columns, new Set(["draft", "review"])), "review")
  assert.equal(openingColumn(columns, new Set(["draft", "done"])), "draft")
  assert.equal(openingColumn(columns, new Set(["draft", "blocked"]), "draft"), "draft")
  // A column chosen once and no longer drawn — emptied, and empty ones are hidden — is not one to open on.
  assert.equal(openingColumn(["blocked", "done"], new Set(["blocked"]), "draft"), "blocked")
  assert.equal(openingColumn(columns, new Set()), "draft")
})
