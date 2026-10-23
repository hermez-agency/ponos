/* What the filters of the Ideas list keep, held to what the list always did.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { counts, filtering, keeps, orderOf, ordered, scopeOf, scopes, statusOf, toneOf } from "./idea-search.ts"

const WEBSITE = "0000000000000000000000000000cafe"
const idea = (title: string, status: string, author: string, project = "", kind = "ticket", category = "") => ({
  title,
  status,
  kind,
  category,
  project,
  author: { kind: author },
})
const IDEAS = [
  idea("calendar", "proposed", "ponos", "", "ticket", "feature"),
  idea("invoice", "kept", "ponos", "", "project", "feature"),
  idea("hours", "proposed", "human", "", "ticket", "ux"),
  idea("sitemap", "discarded", "ponos", WEBSITE, "ticket", "technical"),
  idea("quotation", "ticket", "ponos", "00000000-0000-0000-0000-00000000cafe"),
]
const titles = (filter: object) => IDEAS.filter((one) => keeps(one, filter)).map((one) => one.title)

test("nothing chosen keeps the new ideas, and all keeps every idea", () => {
  assert.deepEqual(titles({}), ["calendar", "hours"])
  assert.deepEqual(titles({ status: "", author: "", project: "" }), ["calendar", "hours"])
  assert.equal(titles({ status: "all" }).length, IDEAS.length)
  assert.equal(statusOf({}), "proposed")
  assert.equal(statusOf({ status: "all" }), "")
  assert.equal(statusOf({ status: "kept" }), "kept")
  assert.equal(filtering({ status: " ", author: "", project: "" }), false)
})

test("the status keeps the ideas in that status", () => {
  assert.deepEqual(titles({ status: "proposed" }), ["calendar", "hours"])
  assert.deepEqual(titles({ status: "ticket" }), ["quotation"])
  assert.equal(filtering({ status: "kept" }), true)
})

test("the category keeps the ideas sorted into it, and none of the unsorted ones", () => {
  assert.deepEqual(titles({ category: "feature", status: "all" }), ["calendar", "invoice"])
  assert.deepEqual(titles({ category: "feature", status: "kept" }), ["invoice"])
  assert.deepEqual(titles({ category: "security" }), [])
  assert.equal(filtering({ category: "ux" }), true)
  assert.equal(counts(IDEAS, { category: "feature" }).proposed, 1)
})

test("the author keeps Ponos's ideas, or ours", () => {
  assert.deepEqual(titles({ author: "human" }), ["hours"])
  assert.deepEqual(titles({ author: "ponos", status: "proposed" }), ["calendar"])
})

test("the project keeps its ideas, with or without the dashes of its id", () => {
  assert.deepEqual(titles({ project: WEBSITE, status: "all" }), ["sitemap", "quotation"])
  assert.deepEqual(titles({ project: "00000000-0000-0000-0000-00000000cafe", status: "all" }), ["sitemap", "quotation"])
})

test("the workspace keeps its ideas, the ideas of a new project among them", () => {
  assert.deepEqual(titles({ project: "workspace", status: "all" }), ["calendar", "invoice", "hours"])
  assert.equal(scopeOf(idea("x", "proposed", "ponos", WEBSITE, "project")), "")
})

test("the counts follow the other filters, not the status", () => {
  assert.deepEqual(counts(IDEAS, { status: "kept", project: "workspace" }), {
    all: 3,
    proposed: 2,
    kept: 1,
    discarded: 0,
    ticket: 0,
  })
  assert.equal(counts(IDEAS, { author: "human" }).all, 1)
})

test("the projects offered are those an idea is for, once each", () => {
  assert.deepEqual(scopes(IDEAS), [WEBSITE])
})

test("a score is red under 40, orange from 40 to 69, green from 70", () => {
  assert.deepEqual([0, 39, 40, 69, 70, 100].map(toneOf), ["red", "red", "orange", "orange", "green", "green"])
  assert.equal(toneOf(null), "unscored")
  assert.equal(toneOf(undefined), "unscored")
})

const scored = [
  { ...idea("newest", "proposed", "ponos"), score: 45 },
  { ...idea("unscored", "proposed", "human"), score: null },
  { ...idea("green", "proposed", "ponos"), score: 88 },
  { ...idea("red", "kept", "ponos"), score: 12 },
  { ...idea("green too", "proposed", "ponos"), score: 88 },
]

test("the colour keeps the ideas of that colour, and not scored is one of them", () => {
  const kept = (score: string) => scored.filter((one) => keeps(one, { score, status: "all" })).map((one) => one.title)
  assert.deepEqual(kept("green"), ["green", "green too"])
  assert.deepEqual(kept("orange"), ["newest"])
  assert.deepEqual(kept("red"), ["red"])
  assert.deepEqual(kept("unscored"), ["unscored"])
  assert.equal(filtering({ score: "green" }), true)
})

test("by relevance the green come first, the unscored last, and equals stay newest first", () => {
  assert.deepEqual(
    ordered(scored, { sorted: "relevance" }).map((one) => one.title),
    ["green", "green too", "newest", "red", "unscored"]
  )
  assert.deepEqual(ordered(scored, { sorted: "newest" }).map((one) => one.title), scored.map((one) => one.title))
})

test("the new ideas rest on relevance, every other list on the newest first", () => {
  assert.equal(orderOf({}), "relevance")
  assert.equal(orderOf({ status: "all" }), "newest")
  assert.equal(orderOf({ status: "proposed" }), "relevance")
  assert.equal(orderOf({ status: "kept" }), "newest")
  assert.equal(orderOf({ status: "proposed", sorted: "newest" }), "newest")
  assert.equal(orderOf({ status: "all", sorted: "relevance" }), "relevance")
})
