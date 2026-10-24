/* What the server refuses with, recognised by the sentence it was said from.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { REFUSALS, SILENT, refusalOf } from "./refusals.ts"

test("a sentence on the list is its own key, with no values", () => {
  assert.deepEqual(refusalOf("nothing to change"), { key: "nothing to change", params: {} })
  for (const template of REFUSALS.filter((one) => !one.includes("{{"))) {
    assert.deepEqual(refusalOf(template), { key: template, params: {} })
  }
})

test("a sentence with a value is recognised whole, and gives the value back", () => {
  assert.deepEqual(refusalOf("“Bug” is named twice"), { key: "“{{name}}” is named twice", params: { name: "Bug" } })
  assert.deepEqual(refusalOf("Check the board every: 5 at the least"), {
    key: "{{label}}: {{minimum}} at the least",
    params: { label: "Check the board every", minimum: "5" },
  })
  assert.deepEqual(refusalOf(SILENT.replace("{{status}}", "500")), { key: SILENT, params: { status: "500" } })
})

test("a sentence the list does not know, or knows only part of, is nobody's", () => {
  assert.equal(refusalOf("something else went wrong"), undefined)
  assert.equal(refusalOf("nothing to change, really"), undefined)
  assert.equal(refusalOf("Rien à modifier."), undefined)
})

test("a value that looks like a pattern is taken as it is", () => {
  assert.deepEqual(refusalOf("no goal with id (.*)"), { key: "no goal with id {{id}}", params: { id: "(.*)" } })
  assert.equal(refusalOf("{{table}}: a list of {name, value}")?.key, "{{table}}: a list of {name, value}")
})
