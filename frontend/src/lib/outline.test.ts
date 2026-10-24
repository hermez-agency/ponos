/* A session in its broad lines, held to what it groups and how long each lasted.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { FOLDED, everythingOpen, isOpen, outline, prepended, toggled } from "./outline.ts"

const said = (label: string, more: object = {}) => ({ label, detail: "", said: true, ...more })
const tool = (label: string, detail = "", more: object = {}) => ({ label, detail, said: false, ...more })

test("each thing the agent said heads the steps that follow it, up to the next", () => {
  const lines = outline([
    said("I read the brief."),
    tool("Read", "README.md"),
    tool("Bash", "ls"),
    said("I generate the patch."),
    tool("Bash", "git diff"),
  ])
  assert.equal(lines.length, 2)
  assert.equal(lines[0].said?.label, "I read the brief.")
  assert.deepEqual(lines[0].steps.map((step) => step.detail), ["README.md", "ls"])
  assert.equal(lines[1].said?.label, "I generate the patch.")
  assert.deepEqual(lines[1].steps.map((step) => step.detail), ["git diff"])
})

test("the steps before anything was said are a group of their own, with nothing said", () => {
  const lines = outline([tool("Read", "a.py"), tool("Read", "b.py"), said("Now I know.")])
  assert.equal(lines.length, 2)
  assert.equal(lines[0].said, undefined)
  assert.equal(lines[0].steps.length, 2)
  assert.equal(lines[1].steps.length, 0)
})

test("the steps that went wrong are counted on their group", () => {
  const lines = outline([
    said("I run the tests."),
    tool("Bash", "make test"),
    tool("Error", "Exit code 1"),
    tool("Error", "Exit code 2"),
    said("Fixed."),
    tool("Bash", "make test"),
  ])
  assert.equal(lines[0].errors, 2)
  assert.equal(lines[1].errors, 0)
})

test("a group lasts until the next is said, and the last one until its last step", () => {
  const lines = outline([
    said("First.", { at: "2026-10-08T10:00:00+00:00" }),
    tool("Bash", "ls", { at: "2026-10-08T10:00:20+00:00" }),
    said("Second.", { at: "2026-10-08T10:01:30+00:00" }),
    tool("Bash", "ls", { at: "2026-10-08T10:02:00+00:00" }),
  ])
  assert.equal(lines[0].seconds, 90)
  assert.equal(lines[1].seconds, 30)
})

test("steps that do not say when give no duration", () => {
  const lines = outline([said("Hello."), tool("Bash", "ls")])
  assert.equal(lines[0].seconds, undefined)
})

test("keys hold when older steps are put before, or the oldest forgotten", () => {
  const page = [said("B", { position: 10 }), tool("Bash", "x", { position: 11 })]
  const earlier = [tool("Read", "a", { position: 8 }), said("A", { position: 9 }), ...page]
  const key = (lines: { key: string; said?: { label: string } }[], label: string) =>
    lines.find((line) => line.said?.label === label)?.key
  assert.equal(key(outline(page), "B"), key(outline(earlier), "B"))

  // A stream with no positions: what it forgot is said by the offset.
  const stream = [said("A"), tool("Bash"), said("B"), tool("Bash")]
  assert.equal(key(outline(stream), "B"), key(outline(stream.slice(2), 2), "B"))
})

test("a group opened stays open, and everything opened opens what comes next too", () => {
  let state = toggled(FOLDED, "said-3")
  assert.equal(isOpen(state, "said-3"), true)
  assert.equal(isOpen(state, "said-9"), false)
  assert.equal(everythingOpen(state), false)

  state = { all: true, flipped: [] }
  assert.equal(isOpen(state, "said-42"), true)
  assert.equal(everythingOpen(state), true)
  state = toggled(state, "said-42")
  assert.equal(isOpen(state, "said-42"), false)
  assert.equal(everythingOpen(state), false)
  assert.equal(isOpen(toggled(state, "said-42"), "said-42"), true)
})

test("older steps go before the ones held, and a position already held is not held twice", () => {
  const read = (detail: string, position: number) => ({ label: "Read", detail, said: false, position })
  const held = [read("c.py", 3), read("d.py", 4)]
  const page = [read("a.py", 1), read("b.py", 2)]
  const once = prepended(page, held)
  assert.deepEqual(once.map((step) => step.position), [1, 2, 3, 4])
  // The same page read twice — two clicks before the first answer — adds nothing the second time.
  assert.deepEqual(prepended(page, once).map((step) => step.position), [1, 2, 3, 4])
  // A page that overlaps what is held keeps one of each position.
  const overlap = [read("b.py", 2), read("c.py", 3)]
  assert.deepEqual(prepended(overlap, held).map((step) => step.position), [2, 3, 4])
})
