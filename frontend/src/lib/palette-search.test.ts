/* What the command palette keeps, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { OFFERED, says, ticketsFor, type Findable } from "./palette-search.ts"
import { terms } from "./ticket-search.ts"

const ticket = (title: string, column = "ready", project = "Ponos", short = "d05cddf6"): Findable => ({
  title,
  column,
  project,
  short,
})

test("an entry is found by what it says, not by letters scattered through it", () => {
  const words = terms("obj")
  assert.ok(says(["Nouvel objectif", "create", "goal"], words))
  assert.ok(says(["Objectifs", "Goals", "page"], words))
  for (const name of ["Opoil", "Portfolio", "Ponos", "jsonld-repository"])
    assert.ok(!says([name, "project"], words))
})

test("every word typed must be said, in any order, accents and case aside", () => {
  assert.ok(says(["Nouvel objectif"], terms("OBJECTIF nouv")))
  assert.ok(says(["Réglages"], terms("reglages")))
  assert.ok(!says(["Nouvel objectif"], terms("objectif projet")))
  assert.ok(says(["Anything"], terms("")))
})

test("tickets are found by their title or their project", () => {
  const board = [
    ticket("Palette lente"),
    ticket("Rien à voir", "ready", "Opoil"),
    ticket("Autre", "ready", "Leadz"),
  ]
  assert.deepEqual(
    ticketsFor(board, "palette").map((one) => one.title),
    ["Palette lente"]
  )
  assert.deepEqual(
    ticketsFor(board, "opoil").map((one) => one.title),
    ["Rien à voir"]
  )
})

test("a short id finds its ticket from four characters, not from two", () => {
  const board = [ticket("Un", "ready", "Ponos", "a1b2c3d4"), ticket("Deux", "ready", "Ponos", "ffa1eeee")]
  assert.deepEqual(
    ticketsFor(board, "a1b2").map((one) => one.title),
    ["Un"]
  )
  assert.deepEqual(ticketsFor(board, "a1"), [])
})

test("no more than a screen of tickets, the open ones first", () => {
  const done = Array.from({ length: 30 }, (_, index) => ticket(`Fini ${index}`, "done"))
  const open = Array.from({ length: 5 }, (_, index) => ticket(`Ouvert ${index}`))
  const shown = ticketsFor([...done, ...open], "")
  assert.equal(shown.length, OFFERED)
  assert.deepEqual(
    shown.slice(0, 5).map((one) => one.title),
    open.map((one) => one.title)
  )
  assert.equal(shown[5].title, "Fini 0")
  assert.ok(ticketsFor([...done, ...open], "ouvert").every((one) => one.column === "ready"))
})
