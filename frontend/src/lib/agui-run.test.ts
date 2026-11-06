/* The body a run posts does not grow with the thread.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { newMessages } from "./agui-run.ts"

const thread = (turns: number) =>
  Array.from({ length: turns * 2 }, (_, i) => ({
    role: i % 2 ? "assistant" : "user",
    content: `turn ${i} ${"x".repeat(10_000)}`,
  }))

test("a run posts the last user message and nothing before it", () => {
  const sent = newMessages(thread(5))
  assert.equal(sent.length, 1)
  assert.equal(sent[0].role, "user")
  assert.match(sent[0].content, /^turn 8 /)
})

test("the posted body is the same size for a short thread and a long one", () => {
  const size = (turns: number) => JSON.stringify(newMessages(thread(turns))).length
  assert.ok(Math.abs(size(2) - size(300)) < 10)
})

test("a thread with no user message posts nothing", () => {
  assert.deepEqual(newMessages([{ role: "assistant", content: "hi" }]), [])
})
