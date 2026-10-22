/* The series of tickets waiting on you, held to the order it takes them in and where it goes next.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { groupOf, nextOf, ordered, previousOf, seriesIn, tally, withSeries, type Queued } from "./series.ts"

const ticket = (id: string, code: string, policy = "ask", priority: number | null = 50, created = "2026-10-01T10:00:00Z"): Queued => ({
  id,
  priority,
  created,
  block: code ? { code, policy } : null,
})

test("a question comes first, then an access, then the rest, and what Ponos is on last", () => {
  const tickets = [
    ticket("waits", "merge.base-red", "wait-base"),
    ticket("retries", "session.killed", "retry:1"),
    ticket("plain", "ticket.empty"),
    ticket("none", ""),
    ticket("access", "access.sudo"),
    ticket("question", "session.question"),
  ]
  assert.deepEqual(
    ordered(tickets).map((one) => one.id),
    ["question", "access", "plain", "none", "waits", "retries"]
  )
  assert.equal(groupOf(ticket("x", "access.credentials")), 1)
})

test("inside a group, the highest priority first, then the oldest; no priority is the middle", () => {
  const tickets = [
    ticket("young", "session.question", "ask", 50, "2026-10-20T10:00:00Z"),
    ticket("old", "session.question", "ask", 50, "2026-10-02T10:00:00Z"),
    ticket("urgent", "session.question", "ask", 90, "2026-10-21T10:00:00Z"),
    ticket("unscored", "session.question", "ask", null, "2026-10-01T10:00:00Z"),
    ticket("low", "session.question", "ask", 10, "2026-09-01T10:00:00Z"),
  ]
  assert.deepEqual(
    ordered(tickets).map((one) => one.id),
    ["urgent", "unscored", "old", "young", "low"]
  )
})

test("next is the first not decided after, then one not yet seen before; none ends the series", () => {
  const ids = ["a", "b", "c", "d"]
  assert.equal(nextOf(ids, {}, null), "a")
  assert.equal(nextOf(ids, {}, "a"), "b")
  assert.equal(nextOf(ids, { b: "done" }, "a"), "c")
  // A skipped one after is still shown: passing it once is not deciding it.
  assert.equal(nextOf(ids, { c: "skipped" }, "b"), "c")
  // Jumped to the last: the ones never seen before it come next.
  assert.equal(nextOf(ids, { d: "done" }, "d"), "a")
  assert.equal(nextOf(ids, { a: "skipped", b: "done", c: "skipped", d: "done" }, "d"), null)
  // A ticket that left the series is looked for from the start.
  assert.equal(nextOf(ids, {}, "gone"), "a")
})

test("previous skips what is decided, and there is none before the first", () => {
  const ids = ["a", "b", "c"]
  assert.equal(previousOf(ids, {}, "c"), "b")
  assert.equal(previousOf(ids, { b: "done" }, "c"), "a")
  assert.equal(previousOf(ids, {}, "a"), null)
  assert.equal(previousOf(ids, { a: "skipped" }, "b"), "a")
})

test("the tally counts what was decided and what was passed over", () => {
  assert.deepEqual(tally(["a", "b", "c", "d"], { a: "done", b: "skipped", c: "done", gone: "done" }), {
    done: 2,
    skipped: 1,
  })
})

test("the address names the series, and keeps everything else as it was written", () => {
  assert.equal(seriesIn("?view=console/tickets/list&series=blocked"), "blocked")
  assert.equal(seriesIn("?series=review"), "review")
  assert.equal(seriesIn("?series=done"), null)
  assert.equal(seriesIn(""), null)
  assert.equal(withSeries("?view=console/tickets/list", "blocked"), "?view=console/tickets/list&series=blocked")
  assert.equal(withSeries("?view=console/tickets/list&series=blocked", "review"), "?view=console/tickets/list&series=review")
  assert.equal(withSeries("?view=console/tickets/list&series=blocked", null), "?view=console/tickets/list")
  assert.equal(withSeries("", "blocked"), "?series=blocked")
  assert.equal(withSeries("?series=blocked", null), "")
})
