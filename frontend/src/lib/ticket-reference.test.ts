import assert from "node:assert/strict"
import { test } from "node:test"

import { ticketNamed } from "./ticket-reference.ts"

const board = [
  { id: "a".repeat(24) + "d05cddf6", short: "d05cddf6", public_id: "PON-142" },
  { id: "b".repeat(32), short: "bbbbbbbb", public_id: "BA-37" },
  { id: "c".repeat(32), short: "cccccccc" },
]

test("a ticket is named by its id, its public id in any case, or its short id", () => {
  assert.equal(ticketNamed(board, "b".repeat(32))?.public_id, "BA-37")
  assert.equal(ticketNamed(board, "PON-142")?.short, "d05cddf6")
  assert.equal(ticketNamed(board, "pon-142")?.short, "d05cddf6")
  assert.equal(ticketNamed(board, " Ba-37 ")?.id, "b".repeat(32))
  assert.equal(ticketNamed(board, "D05CDDF6")?.public_id, "PON-142")
})

test("nothing is named by what no ticket answers to", () => {
  assert.equal(ticketNamed(board, "PON-9"), undefined)
  assert.equal(ticketNamed(board, ""), undefined)
  assert.equal(ticketNamed(board, "ffffffff"), undefined)
})
