/* A card changed on the board meanwhile: said in the page's words, and said once.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { BY_CONSOLE, BY_RUNNER, conflictOf, unshown } from "./conflicts.ts"
import { FRENCH as french } from "./french.ts"

const RUNNER =
  "the runner would have written blocked, but the page says cancelled " +
  "(it said progress when the runner last read it); not overwritten"

/* The columns as the console heads them in French — the vocabulary the toast must speak. */
const COLUMNS: Record<string, string> = { blocked: "Bloqué", cancelled: "Abandonné", running: "En cours" }
const STATUSES: Record<string, string> = { blocked: "blocked", cancelled: "cancelled", progress: "running" }
const named = (status: string) => COLUMNS[STATUSES[status] ?? ""] ?? status

const fill = (template: string, params: Record<string, string>) =>
  template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => params[name] ?? "")

test("the runner's refusal is recognised, with the two statuses it was between", () => {
  assert.deepEqual(conflictOf({ sync_error: RUNNER }), {
    key: BY_RUNNER,
    wanted: "blocked",
    found: "cancelled",
  })
})

test("a page with no status is said to have none, not “no status”", () => {
  const said = conflictOf({
    sync_error:
      "the runner would have written review, but the page says no status " +
      "(it said progress when the runner last read it); not overwritten",
  })
  assert.equal(said?.found, "")
})

test("the console's own refusal takes the move from the card", () => {
  assert.deepEqual(conflictOf({ sync_error: "The board already says Done", sync_status: "review" }), {
    key: BY_CONSOLE,
    wanted: "review",
    found: "Done",
  })
})

test("a sentence it does not know is nobody's", () => {
  assert.equal(conflictOf({ sync_error: "something else" }), undefined)
  assert.equal(conflictOf({}), undefined)
})

test("in French, the toast says it with the columns' words and no English", () => {
  const said = conflictOf({ sync_error: RUNNER })!
  const sentence = fill(french[said.key], { wanted: named(said.wanted), found: named(said.found) })
  assert.equal(sentence, "Ponos voulait le passer en Bloqué, mais il est Abandonné sur le board : laissé tel quel.")
  assert.doesNotMatch(sentence, /\b(runner|page|says|written|blocked|cancelled|progress|overwritten)\b/)
  assert.ok(french[BY_CONSOLE], "the console's refusal has its French too")
})

test("a conflict already shown is not shown again, on this load or the next", () => {
  const cards = [
    { id: "a", sync: "conflict" as const, sync_error: RUNNER },
    { id: "b", sync: "failed" as const, sync_error: "500" },
    { id: "c" },
  ]
  const first = unshown(cards, [])
  assert.deepEqual(
    first.fresh.map((card) => card.id),
    ["a"]
  )
  // Reloaded three times: the same conflict, remembered, is said no more.
  let kept = first.kept
  for (let load = 0; load < 3; load++) {
    const again = unshown(cards, kept)
    assert.deepEqual(again.fresh, [])
    kept = again.kept
  }
  // A new refusal on the same ticket is news.
  const other = RUNNER.replace("cancelled", "done")
  assert.deepEqual(
    unshown([{ id: "a", sync: "conflict", sync_error: other }], kept).fresh.map((card) => card.id),
    ["a"]
  )
})

test("a conflict that was settled is forgotten, so that the next one is said", () => {
  const { kept } = unshown([{ id: "a", sync: "conflict", sync_error: RUNNER }], [])
  const settled = unshown([{ id: "a" }], kept)
  assert.deepEqual(settled.kept, [])
  assert.equal(unshown([{ id: "a", sync: "conflict", sync_error: RUNNER }], settled.kept).fresh.length, 1)
})
