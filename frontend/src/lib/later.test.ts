/* The shortcuts of « Scheduled for », and the moment they leave as.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { fromLocalInput, isoWithOffset, localInput, shortcut, upcoming } from "./later.ts"

// A Friday, at ten past four in the afternoon, wherever the test runs.
const NOW = new Date(2026, 10, 20, 16, 10, 42)

const wall = (moment: Date | null) => (moment ? localInput(isoWithOffset(moment)) : null)

test("each shortcut is a moment to come, to the minute", () => {
  assert.equal(wall(shortcut("hour", NOW)), "2026-11-20T17:10")
  assert.equal(wall(shortcut("tonight", NOW)), "2026-11-20T18:00")
  assert.equal(wall(shortcut("tomorrow", NOW)), "2026-11-21T09:00")
  assert.equal(wall(shortcut("after-tomorrow", NOW)), "2026-11-22T09:00")
  assert.equal(wall(shortcut("monday", NOW)), "2026-11-23T09:00")
})

test("tonight is gone once the evening has begun, and a Monday's next Monday is a week away", () => {
  assert.equal(shortcut("tonight", new Date(2026, 10, 20, 19, 0)), null)
  assert.equal(wall(shortcut("monday", new Date(2026, 10, 23, 8, 0))), "2026-11-30T09:00")
})

test("a moment leaves with the browser's offset and comes back to the same wall time", () => {
  const sent = fromLocalInput("2026-11-21T09:30")
  assert.match(sent, /^2026-11-21T09:30[+-]\d{2}:\d{2}$/)
  assert.equal(Date.parse(sent), new Date(2026, 10, 21, 9, 30).getTime())
  assert.equal(localInput(sent), "2026-11-21T09:30")
  assert.equal(fromLocalInput(""), "")
  assert.equal(localInput("demain"), "")
})

test("only a date to come holds a ticket back", () => {
  const now = NOW.getTime()
  assert.equal(upcoming(isoWithOffset(new Date(now + 60_000)), now), true)
  assert.equal(upcoming(isoWithOffset(new Date(now - 60_000)), now), false)
  assert.equal(upcoming("", now), false)
  assert.equal(upcoming(undefined, now), false)
})
