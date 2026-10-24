/* The search over the board, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 *
 * Node runs this file as it is, and imports `ticket-search.ts` directly, which
 * is why that module imports nothing of its own.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import {
  EMPTY,
  active,
  fold,
  isEmpty,
  marks,
  matchesQuery,
  readQuery,
  terms,
  toggled,
  writeQuery,
  type Searchable,
  type TicketQuery,
} from "./ticket-search.ts"

const NOW = Date.parse("2026-10-12T15:00:00Z")

const ticket = (given: Partial<Searchable> = {}): Searchable => ({
  id: "3f7451680af48149b759f63ad05cddf6",
  short: "d05cddf6",
  title: "Petits moteurs de recherche sur la page Board",
  column: "ready",
  project: "Ponos",
  type: "Code",
  priority: 75,
  model: "opus",
  progress: "",
  pull_request: "",
  runner: "",
  cost: null,
  created: "2026-10-12T09:00:00Z",
  edited: "2026-10-12T09:00:00Z",
  ...given,
})

const query = (given: Partial<TicketQuery> = {}): TicketQuery => ({ ...EMPTY, ...given })
const keeps = (one: Searchable, given: Partial<TicketQuery>) =>
  matchesQuery(one, query(given), {
    now: NOW,
    choices: { type: [{ value: "writing", label: "Rédaction" }, { value: "code", label: "Code" }] },
  })

test("case, accents and punctuation are set aside, on both sides", () => {
  assert.equal(fold("Rédaction — Éditer l'ÉTÉ"), "redaction editer l ete")
  assert.deepEqual(terms("  PETITS-moteurs  petits "), ["petits", "moteurs"])
  const french = ticket({ title: "Créer la page « Réglages »" })
  assert.equal(keeps(french, { text: "reglages" }), true)
  assert.equal(keeps(french, { text: "RÉGLAGES créer" }), true)
  assert.equal(keeps(french, { text: "réglages supprimer" }), false)
})

test("the words are looked for in the title, the runner's line, the pull request and the project", () => {
  assert.equal(keeps(ticket({ progress: "RESULT: ok — barre de recherche ajoutée" }), { text: "ajoutee" }), true)
  assert.equal(keeps(ticket({ pull_request: "https://github.com/x/ponos/pull/201" }), { text: "#201" }), true)
  assert.equal(keeps(ticket(), { text: "ponos moteurs" }), true)
  assert.equal(keeps(ticket(), { text: "brief" }), false)
})

test("a ticket is found by its id, its branch or its Notion address, and only that one", () => {
  assert.equal(keeps(ticket(), { text: "#d05c" }), true)
  assert.equal(keeps(ticket(), { text: "d05" }), false, "three characters are not an id")
  const branch = "ticket/ponos-petits-moteurs-de-recherche-sur-la-d05cddf6"
  assert.equal(keeps(ticket(), { text: branch }), true)
  assert.equal(keeps(ticket({ short: "aaaa1111" }), { text: branch }), false)
  const address = "https://app.notion.com/p/Ponos-Petits-moteurs-3f7451680af48149b759f63ad05cddf6"
  assert.equal(keeps(ticket(), { text: address }), true)
  assert.equal(keeps(ticket({ id: "0".repeat(32) }), { text: address }), false)
})

test("the filters combine: every one of them must hold, with the words", () => {
  const one = ticket({ type: "Rédaction", column: "review", priority: 100, pull_request: "https://x/pull/3" })
  assert.equal(keeps(one, { type: ["writing"] }), true, "the key finds the board's own spelling")
  assert.equal(keeps(one, { type: ["code"] }), false)
  assert.equal(keeps(one, { type: ["code", "writing"], status: ["review", "done"] }), true)
  assert.equal(keeps(one, { type: ["writing"], status: ["done"] }), false)
  assert.equal(keeps(one, { priority: ["100"], only: ["pr"], text: "moteurs" }), true)
  assert.equal(keeps(one, { priority: ["75"] }), false, "a score is the score, not a band")
  assert.equal(keeps(ticket({ priority: null }), { priority: ["50"] }), false, "no column is no score")
  assert.equal(keeps(one, { priority: ["100"], only: ["pr"], text: "absent" }), false)
  assert.equal(keeps(ticket(), { only: ["pr"] }), false)
  assert.equal(keeps(ticket(), { project: ["Website"] }), false)
  assert.equal(keeps(ticket({ type: "" }), { type: ["code"] }), false, "no type is not every type")
})

test("the switches: credits, sync, cost and period", () => {
  const waiting = ticket({ held: { reason: "budget", detail: "18:00" } })
  assert.equal(keeps(waiting, { only: ["credits"] }), true)
  assert.equal(keeps(ticket({ held: { reason: "next", detail: "" } }), { only: ["credits"] }), false)
  assert.equal(keeps(ticket({ sync: "failed" }), { only: ["sync"] }), true)
  assert.equal(keeps(ticket({ cost: 7.5 }), { cost: 5 }), true)
  assert.equal(keeps(ticket({ cost: 2 }), { cost: 5 }), false)
  assert.equal(keeps(ticket({ cost: null }), { cost: 1 }), false)
  const old = ticket({ created: "2026-09-01T09:00:00Z", edited: "2026-10-01T09:00:00Z" })
  assert.equal(keeps(old, { since: "30d" }), true, "touched recently counts, not only created")
  assert.equal(keeps(old, { since: "7d" }), false)
  assert.equal(keeps(ticket({ edited: "2026-10-12T12:00:00Z" }), { since: "today" }), true)
})

test("the query goes into the address and comes back the same", () => {
  const given = query({
    text: "barre de recherche",
    type: ["code", "writing"],
    status: ["ready"],
    priority: ["Très haute"],
    project: ["Site & blog"],
    only: ["pr", "credits"],
    cost: 5,
    since: "7d",
  })
  const written = writeQuery("?view=console/tickets/list&variant=table", given)
  assert.ok(written.startsWith("?view=console/tickets/list&variant=table&q="), written)
  assert.deepEqual(readQuery(written), given)
  // Its own parameters are replaced, the others kept, and an empty query leaves no trace.
  assert.equal(writeQuery(written, EMPTY), "?view=console/tickets/list&variant=table")
  assert.equal(writeQuery("?view=console/projects/read/x&tab=tickets&q=old", query({ text: "new" })),
    "?view=console/projects/read/x&tab=tickets&q=new")
  // The router writes the address again as it reads it, commas encoded.
  assert.deepEqual(readQuery("?type=code%2Cexternal&priority=Urgent"),
    query({ type: ["code", "external"], priority: ["Urgent"] }))
  // What the address cannot mean is dropped rather than half read.
  assert.deepEqual(readQuery("?only=pr,nonsense&since=yesterday&cost=abc"), query({ only: ["pr"] }))
})

test("a stopped ticket is found by the cause it stopped on, and the address keeps it", () => {
  const refused = ticket({ column: "blocked", block: { code: "merge.refused" } })
  const asked = ticket({ column: "blocked", block: { code: "session.question" } })
  const running = ticket({ column: "running" })
  assert.equal(keeps(refused, { block: ["merge.refused"] }), true)
  assert.equal(keeps(refused, { block: ["merge.refused", "session.question"] }), true)
  assert.equal(keeps(asked, { block: ["merge.refused"] }), false)
  assert.equal(keeps(running, { block: ["merge.refused"] }), false)
  assert.equal(keeps(running, {}), true)
  const given = query({ block: ["merge.refused", "worktree.residue"] })
  assert.deepEqual(readQuery(writeQuery("", given)), given)
  assert.equal(active(given), 1)
})

test("a code ticket is found by its sub-type, and the address keeps it", () => {
  const bug = ticket({ subtype: "bug" })
  const docs = ticket({ subtype: "docs" })
  const none = ticket({})
  assert.equal(keeps(bug, { subtype: ["bug"] }), true)
  assert.equal(keeps(docs, { subtype: ["bug", "docs"] }), true)
  assert.equal(keeps(docs, { subtype: ["bug"] }), false)
  assert.equal(keeps(none, { subtype: ["bug"] }), false)
  assert.equal(keeps(none, {}), true)
  const given = query({ subtype: ["bug", "security"] })
  assert.equal(writeQuery("", given), "?subtype=bug,security")
  assert.deepEqual(readQuery(writeQuery("", given)), given)
  assert.equal(active(given), 1)
})

test("what is on, counted", () => {
  assert.equal(isEmpty(EMPTY), true)
  assert.equal(isEmpty(query({ text: "  " })), true)
  assert.equal(isEmpty(query({ text: "x" })), false)
  assert.equal(active(query({ text: "x", type: ["code", "writing"], only: ["pr"], since: "7d" })), 3)
  assert.deepEqual(toggled(["a", "b"], "a"), ["b"])
  assert.deepEqual(toggled(["a"], "b"), ["a", "b"])
})

test("the words are marked where they are, accents and all", () => {
  assert.deepEqual(marks("Rédaction du README", ["redaction"]), [[0, 9]])
  assert.deepEqual(marks("Board board", ["board"]), [[0, 5], [6, 11]])
  assert.deepEqual(marks("petits-moteurs", ["petits", "s moteurs"]), [[0, 14]])
  assert.deepEqual(marks("rien", ["absent"]), [])
  assert.deepEqual(marks("", ["x"]), [])
})

test("a goal keeps the tickets that serve it, with the project and the words, and the address names it by its id", () => {
  const goal = "29c451680af4810a8e02f65c6bd45a85"
  const serving = ticket({ goal_id: goal })
  assert.equal(keeps(serving, { goal: [goal] }), true)
  assert.equal(keeps(ticket(), { goal: [goal] }), false, "no goal is not every goal")
  assert.equal(keeps(serving, { goal: [goal], project: ["Ponos"], text: "moteurs" }), true)
  assert.equal(keeps(serving, { goal: [goal], project: ["Website"] }), false)
  assert.equal(writeQuery("", query({ goal: [goal] })), `?goal=${goal}`)
  assert.deepEqual(readQuery(`?goal=${goal}&project=Ponos`), query({ goal: [goal], project: ["Ponos"] }))
  assert.equal(active(query({ goal: [goal] })), 1)
})
