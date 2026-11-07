/* What the console reads in markdown, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 *
 * Node runs this file as it is: it strips the types and imports `markdown.ts`
 * directly, which is why that module imports nothing of its own.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { blocks, spans, type Block } from "./markdown.ts"

const markers = (text: string) =>
  blocks(text).map((block) => (block.kind === "item" ? block.marker : block.kind))

test("a numbered list written 1. 1. 1. is counted", () => {
  assert.deepEqual(markers("1. un\n1. deux\n1. trois"), ["1.", "2.", "3."])
})

test("a list starting at 3 still starts at 3", () => {
  assert.deepEqual(markers("3. trois\n7. quatre\n1. cinq"), ["3.", "4.", "5."])
})

test("a blank line between items does not end the list", () => {
  assert.deepEqual(markers("1. un\n\n1. deux"), ["1.", "2."])
})

test("anything else ends it, and the next list starts over", () => {
  assert.deepEqual(markers("1. un\n1. deux\n\nEntre deux.\n\n1. un"), [
    "1.",
    "2.",
    "paragraph",
    "1.",
  ])
  assert.deepEqual(markers("1. un\n## Titre\n1. un"), ["1.", "heading", "1."])
  assert.deepEqual(markers("1. un\n- puce\n1. un"), ["1.", "–", "1."])
})

test("a nested list counts on its own, and its parent goes on after it", () => {
  assert.deepEqual(markers("1. un\n  1. a\n  1. b\n1. deux\n  1. a"), [
    "1.",
    "1.",
    "2.",
    "2.",
    "1.",
  ])
})

test("a table is read with its head, its alignments and its rows", () => {
  const [table] = blocks("| a | b | c |\n|---|:-:|--:|\n| 1 | 2 | 3 |\n| 4 |\n")
  assert.deepEqual(table, {
    kind: "table",
    head: ["a", "b", "c"],
    align: [null, "center", "right"],
    rows: [
      ["1", "2", "3"],
      ["4", "", ""],
    ],
  } satisfies Block)
})

test("a table without its outer pipes, or with an escaped one, is still a table", () => {
  const [table] = blocks("a | b\n--- | ---\n`x \\| y` | 2")
  assert.equal(table.kind, "table")
  if (table.kind === "table") assert.deepEqual(table.rows, [["`x | y`", "2"]])
})

test("a table ends at a blank line, and pipes without a rule under them are text", () => {
  assert.deepEqual(markers("| a | b |\n|---|---|\n| 1 | 2 |\n\nAprès."), ["table", "paragraph"])
  assert.deepEqual(markers("| a | b |\n| 1 | 2 |"), ["paragraph"])
  assert.deepEqual(markers("| a | b |\n|---|"), ["paragraph"])
})

test("the brief of the ticket reads as a list, a table and a bold", () => {
  const brief = "1. un\n1. deux\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**gras avec `code` dedans**"
  assert.deepEqual(markers(brief), ["1.", "2.", "table", "paragraph"])
})

test("a bold may hold code and a link", () => {
  assert.deepEqual(spans("**gras avec `code` dedans**"), [
    {
      kind: "strong",
      children: [
        { kind: "text", text: "gras avec " },
        { kind: "code", text: "code" },
        { kind: "text", text: " dedans" },
      ],
    },
  ])
  assert.deepEqual(spans("**voir [la page](https://x.y)**"), [
    {
      kind: "strong",
      children: [
        { kind: "text", text: "voir " },
        { kind: "link", href: "https://x.y", children: [{ kind: "text", text: "la page" }] },
      ],
    },
  ])
})

test("an emphasis may hold code and a bold", () => {
  assert.deepEqual(spans("*mis en `review` et **pas** ailleurs*"), [
    {
      kind: "em",
      children: [
        { kind: "text", text: "mis en " },
        { kind: "code", text: "review" },
        { kind: "text", text: " et " },
        { kind: "strong", children: [{ kind: "text", text: "pas" }] },
        { kind: "text", text: " ailleurs" },
      ],
    },
  ])
})

test("a code span holds nothing but its text", () => {
  assert.deepEqual(spans("`**pas gras**`"), [{ kind: "code", text: "**pas gras**" }])
  // A star inside code does not close the bold around it.
  assert.deepEqual(spans("**a `*` b**"), [
    {
      kind: "strong",
      children: [
        { kind: "text", text: "a " },
        { kind: "code", text: "*" },
        { kind: "text", text: " b" },
      ],
    },
  ])
})

test("stars that open nothing stay as they were written", () => {
  assert.deepEqual(spans("2 * 3 * 4"), [{ kind: "text", text: "2 * 3 * 4" }])
  assert.deepEqual(spans("**ouvert\nfermé**"), [{ kind: "text", text: "**ouvert\nfermé**" }])
  assert.deepEqual(spans("un `seul"), [{ kind: "text", text: "un `seul" }])
})

test("markup is text, never markup", () => {
  assert.deepEqual(spans("**<b>x</b>**"), [
    { kind: "strong", children: [{ kind: "text", text: "<b>x</b>" }] },
  ])
  assert.deepEqual(spans("[x](javascript:alert(1))"), [
    { kind: "link", href: "javascript:alert(1", children: [{ kind: "text", text: "x" }] },
    { kind: "text", text: ")" },
  ])
})

test("a file a page carried is read as its block, and ends a list", () => {
  const block = "0123456789abcdef0123456789abcdef"
  const brief = `1. un\n[image attached to the ticket: capture.png (block ${block})]\n1. un`
  assert.deepEqual(markers(brief), ["1.", "attached", "1."])
  assert.deepEqual(blocks(brief)[1], {
    kind: "attached",
    file: "image",
    label: "capture.png",
    block,
  } satisfies Block)
})
