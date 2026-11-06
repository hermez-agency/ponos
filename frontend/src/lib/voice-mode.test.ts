import assert from "node:assert/strict"
import test from "node:test"

import {
  QUIET_MS,
  advance,
  finished,
  interrupts,
  interruption,
  mayHaveGrown,
  opened,
  unsaid,
  wordsOf,
} from "./voice-mode.ts"

const run = (levels: number[], ms = 80) => levels.reduce((gate, level) => advance(gate, level, ms), opened())

test("a sentence ends after speech and a silence, not before", () => {
  const talking = run(Array(10).fill(0.5))
  assert.equal(talking.heard, true)
  assert.equal(finished(talking), false)
  const quiet = run([...Array(10).fill(0.5), ...Array(Math.ceil(QUIET_MS / 80)).fill(0)])
  assert.equal(finished(quiet), true)
})

test("silence alone never ends anything, and a click is not speech", () => {
  assert.equal(finished(run(Array(60).fill(0))), false)
  const click = run([0.9, 0, ...Array(40).fill(0)])
  assert.equal(click.heard, false)
  assert.equal(finished(click), false)
})

test("a pause inside a sentence starts the silence over", () => {
  const gate = run([...Array(8).fill(0.5), ...Array(10).fill(0), ...Array(8).fill(0.5), 0])
  assert.equal(gate.quiet, 80)
  assert.equal(finished(gate), false)
})

test("only a loud, lasting sound talks over the voice", () => {
  let so_far = 0
  for (let i = 0; i < 3; i++) so_far = interruption(so_far, 0.9, 80)
  assert.equal(interrupts(so_far), false)
  so_far = interruption(so_far, 0.1, 80)
  assert.equal(so_far, 0, "the echo of the voice resets it")
  for (let i = 0; i < 5; i++) so_far = interruption(so_far, 0.9, 80)
  assert.equal(interrupts(so_far), true)
})

test("what is left to say, and the words of a message", () => {
  assert.deepEqual(unsaid(["a", "b", "c"], 2), ["c"])
  assert.equal(
    wordsOf([{ type: "thinking", content: "x" }, { type: "text", content: "Bonjour" }, { type: "tool-call" }]),
    "Bonjour"
  )
  assert.equal(mayHaveGrown("Bonjour", "Bonjour tout"), false)
  assert.equal(mayHaveGrown("Bonjour", "Bonjour tout le monde."), true)
})
