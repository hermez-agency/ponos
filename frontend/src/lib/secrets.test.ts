/* What the bar warns about before a message reaches a ticket.
 *
 *     npm test          (node --test, nothing to install)
 *
 * The same sentences as `tests/run.py` reads through `redaction.found`: the
 * page and the runner have to agree on what a secret is.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { secretsIn } from "./secrets.ts"

test("a labelled password is seen, in English and in French", () => {
  assert.deepEqual(secretsIn("mot de passe : hunter2"), ["password"])
  assert.deepEqual(secretsIn("password=S3cr3t!"), ["password"])
  assert.deepEqual(secretsIn("Le mot de passe npm de l'agence est Hz!2026kpl"), ["password"])
  assert.deepEqual(secretsIn('mdp: "azerty123" merci'), ["password"])
  assert.deepEqual(secretsIn("la clé API : abcd1234"), ["password"])
})

test("a token is seen by its shape, and a password inside an address", () => {
  assert.deepEqual(secretsIn("voici ghp_abcdefghijklmnopqrstuvwxyz0123456789"), ["token"])
  assert.deepEqual(secretsIn("sk-ant-api03-abcdefghijklmnopqrstuvwxyz"), ["token"])
  assert.deepEqual(secretsIn("npm_abcdefghijklmnopqrstuvwxyz0123456789"), ["token"])
  assert.deepEqual(secretsIn("git clone https://salva:p4ss@github.com/x/y.git"), ["address"])
})

test("what only talks about a secret, and the ids a report is full of, are not one", () => {
  assert.deepEqual(secretsIn("le token est expiré, refais-le"), [])
  assert.deepEqual(secretsIn("le secret est dans le coffre"), [])
  assert.deepEqual(secretsIn("Oui, vas-y avec le mot de passe que tu as."), [])
  assert.deepEqual(secretsIn("commit 8df7c20a1b2c3d4e5f60718293a4b5c6d7e8f901, session 3fe451680af4819c8f1bdb25215b6ff7"), [])
  assert.deepEqual(secretsIn("https://github.com/SalvadorCardona/ticket-runner/pull/284"), [])
})
