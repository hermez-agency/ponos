/* A ticket's score, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { readScore, scoreTone } from "./priority.ts"

test("a score is drawn grey-blue at 0, green at 25, yellow at 50, orange at 75, red at 100", () => {
  assert.deepEqual(scoreTone(0), { hue: 215, saturation: 22 })
  assert.deepEqual(scoreTone(25), { hue: 142, saturation: 58 })
  assert.deepEqual(scoreTone(50), { hue: 48, saturation: 92 })
  assert.deepEqual(scoreTone(75), { hue: 27, saturation: 92 })
  assert.deepEqual(scoreTone(100), { hue: 0, saturation: 78 })
})

test("a score between two stops is a shade between them, and one outside is the end it passed", () => {
  const between = scoreTone(60)
  assert.ok(between.hue < 48 && between.hue > 27, String(between.hue))
  assert.deepEqual(scoreTone(150), scoreTone(100))
  assert.deepEqual(scoreTone(-5), scoreTone(0))
})

test("a typed score is a whole number from 0 to 100, nothing typed is none, anything else is refused", () => {
  assert.equal(readScore("75"), 75)
  assert.equal(readScore(" 0 "), 0)
  assert.equal(readScore(100), 100)
  assert.equal(readScore("62,6"), 63)
  assert.equal(readScore(""), null)
  assert.equal(readScore(undefined), null)
  assert.equal(readScore("101"), undefined)
  assert.equal(readScore("-1"), undefined)
  assert.equal(readScore("vite"), undefined)
})
