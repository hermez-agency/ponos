/* What a card in progress says of the phase it is in.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { reading, type Phase } from "./phase.ts"

const said = (value: { key: string; params: Record<string, string> } | null) =>
  value ? value.key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => value.params[name]) : null

const at = Date.parse("2026-10-23T12:00:00Z")
const phase = (key: Phase["key"], detail = "", since = "2026-10-23T11:50:00+00:00"): Phase => ({
  key,
  detail,
  since,
})

test("every long phase has words of its own", () => {
  const url = "https://github.com/x/y/pull/371"
  assert.equal(said(reading(phase("checks", url), at)!.said), "waiting for the CI of PR #371")
  assert.equal(said(reading(phase("repair", url), at)!.said), "fixing the CI of PR #371")
  assert.equal(said(reading(phase("repair", "npm test"), at)!.said), "fixing the CI")
  assert.equal(said(reading(phase("rebase", "main"), at)!.said), "rebasing onto main")
  assert.equal(said(reading(phase("local-ci", "npm test"), at)!.said), "running the CI here")
  assert.equal(said(reading(phase("resolve", "main"), at)!.said), "resolving the conflicts with main")
})

test("a session, or its start, is left to its steps", () => {
  assert.equal(reading(phase("session"), at)!.said, null)
  assert.equal(reading(phase("starting"), at)!.said, null)
})

test("only the phases without a session are quiet", () => {
  for (const key of ["rebase", "local-ci", "checks"] as const) assert.equal(reading(phase(key), at)!.quiet, true)
  for (const key of ["starting", "session", "repair", "resolve"] as const)
    assert.equal(reading(phase(key), at)!.quiet, false)
})

test("a start is young for two minutes, then it is not", () => {
  const started = (since: string) => reading(phase("starting", "", since), at)!
  assert.equal(started("2026-10-23T11:59:00Z").young, true)
  assert.equal(started("2026-10-23T11:58:00Z").young, false)
  assert.equal(started("2026-10-23T11:50:00Z").seconds, 600)
})

test("no phase, or one with no date, reads as nothing", () => {
  assert.equal(reading(null, at), null)
  assert.equal(reading(phase("checks", "", "nonsense"), at), null)
})
