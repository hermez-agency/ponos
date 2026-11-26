/* What a search over the projects keeps, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { filtering, keeps } from "./project-search.ts"

const LEADZ = { name: "Leadz", kind: "code", work: "code work" }
const DOSSIER = { name: "Dossier Été", kind: "document", work: "document work" }
const names = (filter: object) => [LEADZ, DOSSIER].filter((p) => keeps(p, filter)).map((p) => p.name)

test("nothing typed keeps every project", () => {
  assert.deepEqual(names({}), ["Leadz", "Dossier Été"])
  assert.deepEqual(names({ q: "  ", type: "" }), ["Leadz", "Dossier Été"])
  assert.equal(filtering({ q: " ", type: "" }), false)
})

test("a part of the name finds a project, whatever the case and the accents", () => {
  assert.deepEqual(names({ q: "LEA" }), ["Leadz"])
  assert.deepEqual(names({ q: "ete" }), ["Dossier Été"])
  assert.deepEqual(names({ q: "dossier ÉTÉ" }), ["Dossier Été"])
  assert.deepEqual(names({ q: "nope" }), [])
})

test("the type keeps the projects of that type", () => {
  assert.deepEqual(names({ type: "code" }), ["Leadz"])
  assert.deepEqual(names({ type: "document" }), ["Dossier Été"])
  assert.equal(filtering({ type: "code" }), true)
})

test("the words may name the type, and a name and a type are combined", () => {
  assert.deepEqual(names({ q: "document" }), ["Dossier Été"])
  assert.deepEqual(names({ q: "d", type: "code" }), ["Leadz"])
  assert.deepEqual(names({ q: "lea", type: "document" }), [])
})

test("an archived project is hidden, and shown once the archived ones are asked for", () => {
  const ARCHIVED = { name: "Vieux site", kind: "code", work: "code work", shelved: true }
  const all = (filter: object) => [LEADZ, DOSSIER, ARCHIVED].filter((p) => keeps(p, filter)).map((p) => p.name)
  assert.deepEqual(all({}), ["Leadz", "Dossier Été"])
  assert.deepEqual(all({ q: "vieux" }), [])
  assert.deepEqual(all({ archived: "1" }), ["Leadz", "Dossier Été", "Vieux site"])
  assert.deepEqual(all({ archived: "1", q: "vieux" }), ["Vieux site"])
  assert.deepEqual(all({ archived: "1", type: "document" }), ["Dossier Été"])
  assert.equal(filtering({ archived: "1" }), true)
  assert.equal(filtering({ archived: "" }), false)
})
