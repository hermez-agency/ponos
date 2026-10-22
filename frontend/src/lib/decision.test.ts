/* The Decide tab's decisions, and a blocked ticket's quick replies, held to what they say.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import {
  CATEGORIES,
  LABELS,
  actionOf,
  answersIn,
  arranged,
  askedAt,
  away,
  decisionTabOf,
  categoryOf,
  immediate,
  itemsOf,
  keyOf,
  labelOf,
  promptOf,
  quiet,
  repliesOf,
  typedOf,
  prefilled,
  sendable,
  titlesIn,
  tone,
  type Offer,
} from "./decision.ts"

const offer = (key: string, needs: Offer["needs"] = "", text = "", number = 0): Offer => ({
  key,
  column: "ready",
  needs,
  text,
  number,
})

test("a blocked card is unblocked, a card in review is decided, and nothing else asks", () => {
  assert.equal(actionOf("blocked"), "Unblock")
  assert.equal(actionOf("review"), "Decide")
  assert.equal(actionOf("ready"), null)
  assert.equal(actionOf("done"), null)
})

test("a blocked ticket opens on its discussion, one in review on Decide, and no other asks", () => {
  assert.equal(decisionTabOf("blocked"), "discussion")
  assert.equal(decisionTabOf("review"), "decide")
  for (const column of ["draft", "ready", "running", "validated", "failed", "done", "cancelled"])
    assert.equal(decisionTabOf(column), null, column)
})

test("every category the runner names has a name, and an unknown one reads as stuck", () => {
  for (const key of ["question", "access", "manual", "credits", "ci", "conflict", "split", "other"])
    assert.ok(CATEGORIES[key], key)
  assert.equal(categoryOf("weather"), "Stuck")
  assert.equal(categoryOf(undefined), "Stuck")
})

test("every key the runner offers has a button, and an option is called by its words", () => {
  for (const key of [
    "yes", "close", "answer", "done-retry", "retry", "model", "instruct", "split", "abandon", "other",
    "validate", "rework", "fix-ci", "add-tests", "screenshots", "rebase", "caveat", "reject",
  ])
    assert.ok(LABELS[key], key)
  assert.equal(labelOf(offer("option", "", "Use Dokploy", 1)), "Use Dokploy")
  assert.equal(labelOf(offer("retry")), "Run it again")
})

test("giving a ticket up says the column it is filed in", () => {
  assert.equal(labelOf({ ...offer("abandon", "note"), column: "done" }), "Abandon — move to done")
  assert.equal(labelOf({ ...offer("abandon", "note"), column: "cancelled" }), "Abandon — move to cancelled")
})

test("a click is enough only for what needs nothing typed", () => {
  assert.ok(immediate(offer("yes")))
  assert.ok(immediate(offer("validate")))
  assert.ok(!immediate(offer("abandon", "note")))
  assert.ok(!immediate(offer("other", "text")))
  assert.ok(!immediate(offer("model", "model")))
})

test("an instruction needs words, a note does not, a model needs a model", () => {
  assert.ok(!sendable(offer("other", "text"), "   "))
  assert.ok(sendable(offer("other", "text"), "Use the key in 1Password"))
  assert.ok(sendable(offer("abandon", "note"), ""))
  assert.ok(!sendable(offer("model", "model"), "", ""))
  assert.ok(sendable(offer("model", "model"), "", "opus"))
  assert.ok(!sendable(offer("split", "titles"), "\n  \n"))
  assert.ok(sendable(offer("split", "titles"), "The API\n\nThe page"))
})

test("a ready-made instruction and the proposed sub-tickets open the field, nothing else does", () => {
  assert.equal(prefilled(offer("fix-ci", "text", "Fix the checks.")), "Fix the checks.")
  assert.equal(prefilled(offer("split", "titles", "A\nB")), "A\nB")
  assert.equal(prefilled(offer("abandon", "note", "ignored")), "")
  assert.deepEqual(titlesIn(" A \n\nB\n"), ["A", "B"])
})

test("no button looks chosen before a click, and the one chosen is full — in red for a way out", () => {
  for (const one of [offer("option", "", "x", 1), offer("validate"), offer("other", "text"), offer("reject", "note")])
    assert.equal(tone(one, false), "outline", one.key)
  assert.equal(tone(offer("rework", "text"), true), "default")
  assert.equal(tone(offer("abandon", "note"), true), "destructive")
  assert.ok(away(offer("reject", "note")) && away(offer("abandon", "note")) && !away(offer("retry")))
})

test("the ways out come last, apart, and every button has its key up to 9", () => {
  const offers = [offer("option", "", "x", 1), offer("abandon", "note"), offer("option", "", "y", 2), offer("other", "text")]
  const { forward, out } = arranged(offers)
  assert.deepEqual(forward.map((one) => one.text || one.key), ["x", "y", "other"])
  assert.deepEqual(out.map((one) => one.key), ["abandon"])
  assert.deepEqual(arranged([offer("validate"), offer("rework", "text")]).out, [])
  assert.equal(keyOf(1), "1")
  assert.equal(keyOf(9), "9")
  assert.equal(keyOf(10), "")
})

test("a yes-no question is answered yes or no, and run again as it is", () => {
  const asked = [offer("yes"), offer("answer", "text"), offer("instruct", "text"), offer("abandon", "note"), offer("other", "text")]
  const replies = repliesOf("blocked", asked)
  assert.deepEqual(replies.map((reply) => reply.label), ["Yes", "No", "Run it again as it is"])
  assert.equal(replies[1].offer?.key, "answer")
  assert.equal(replies[1].text, "No")
  // No retry on offer: running it again as it is is the plain move back to Ready.
  assert.equal(replies[2].offer, undefined)
  assert.deepEqual(repliesOf("review", asked), [])
})

test("a choice is one reply per option, in its own words, and a close proposal closes", () => {
  const options = [offer("option", "", "Buy the Starter Business Email plan for hermez.dev (0,39 €/month)", 1), offer("option", "", "No purchase", 2), offer("retry", "note")]
  const replies = repliesOf("blocked", options)
  assert.deepEqual(replies.map((reply) => reply.label), [options[0].text, "No purchase", "Run it again as it is"])
  assert.equal(replies[2].offer?.key, "retry")
  const closing = repliesOf("blocked", [offer("yes"), offer("close"), offer("answer", "text"), offer("other", "text")])
  assert.deepEqual(closing.map((reply) => reply.label), ["Yes, close it", "No", "Run it again as it is"])
})

test("a sentence typed under the question is its answer, or an instruction where it has none", () => {
  assert.equal(typedOf([offer("yes"), offer("answer", "text"), offer("other", "text")])?.key, "answer")
  assert.equal(typedOf([offer("retry"), offer("other", "text")])?.key, "other")
  assert.equal(typedOf([offer("retry")]), null)
})

test("the run's lines in passing are quiet, and are not Ponos answering", () => {
  const talk = [
    { role: "runner", text: "🧠 Model chosen automatically — opus\nA large change." },
    { role: "you", text: "Go." },
    { role: "runner", text: "🙋 Stuck — branch ready\nWhich host?" },
    { role: "runner", text: "↩️ Back in the queue" },
  ]
  assert.ok(quiet("runner", talk[0].text))
  assert.ok(!quiet("you", talk[0].text), "only the runner speaks in passing")
  assert.ok(!quiet("runner", talk[2].text))
  assert.equal(answersIn(talk), 1)
  assert.equal(askedAt(talk), 2)
  assert.equal(askedAt(talk.slice(0, 2)), -1)
})

test("an answer's field asks for an answer, the others for what they need", () => {
  assert.equal(promptOf(offer("answer", "text")), "Your answer")
  assert.equal(promptOf(offer("instruct", "text")), "The instruction the next session reads")
  assert.equal(promptOf(offer("model", "model")), "A note, if you want one")
})

test("what was done is split into its lines, without their bullets", () => {
  assert.deepEqual(itemsOf(undefined), [])
  assert.deepEqual(itemsOf("branch ready"), ["branch ready"])
  assert.deepEqual(itemsOf("- one\n* two\n\n  three"), ["one", "two", "three"])
  assert.deepEqual(itemsOf("PR opened; CI green"), ["PR opened", "CI green"])
})
