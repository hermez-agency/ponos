/* What the page does with a ticket's result before it reaches the clipboard or a file. */

import assert from "node:assert/strict"
import { test } from "node:test"

import { changes, fileName, isDocument, isFinished, missionText, plainText } from "./result.ts"

test("the text copied is the post without its marks, lines and lists kept", () => {
  const post = "# Titre\n\nTrois choses **apprises** en _livrant_ :\n\n* petit\n- [x] souvent\n\n> seul\n\n---\n\nVoir [le site](https://hermez.dev)."
  assert.equal(
    plainText(post),
    "Titre\n\nTrois choses apprises en livrant :\n\n- petit\n- souvent\n\nseul\n\nVoir le site (https://hermez.dev)."
  )
})

test("code stays as it was written, and a table is its cells between tabs", () => {
  assert.equal(plainText("```sh\n**not bold**\n```"), "**not bold**")
  assert.equal(plainText("| Gravité | Constat |\n|---|:--|\n| Haute | `XSS` |"), "Gravité\tConstat\nHaute\tXSS")
  assert.equal(plainText("snake_case_name stays"), "snake_case_name stays")
})

test("a file is named after the ticket", () => {
  assert.equal(fileName("Écris un post LinkedIn sur l'IA !", "md"), "ecris-un-post-linkedin-sur-l-ia.md")
  assert.equal(fileName("???", "pdf"), "result.pdf")
})

test("a report is a document, a change is not", () => {
  assert.equal(isDocument("Writing", "code"), true)
  assert.equal(isDocument("Code", "code"), false)
  assert.equal(isDocument("", "document"), true)
  assert.equal(isDocument("", "code"), false)
})

test("the work is over in review, once validated and done — not before, nor cancelled", () => {
  for (const column of ["review", "validated", "done"]) assert.equal(isFinished(column), true)
  for (const column of ["draft", "ready", "running", "blocked", "paused", "cancelled"]) assert.equal(isFinished(column), false)
})

test("the mission is drawn without the heading that says it again", () => {
  assert.equal(missionText("## Mission\n\n## Contexte\nUn texte."), "## Contexte\nUn texte.")
  assert.equal(missionText("\n# 1. Mission :\n\n### **Mission**\n\nÉcris."), "Écris.")
  assert.equal(missionText("## Missions passées\n\nRien."), "## Missions passées\n\nRien.")
  assert.equal(missionText("Écris.\n\n## Mission\nplus bas"), "Écris.\n\n## Mission\nplus bas")
})

test("the changes are the journal's report, without its history nor the pull request's line", () => {
  const journal =
    "**Result:** ✅ done\n\n**Pull request:** https://github.com/h/p/pull/1\n\nWhat changed: a tab.\n\n### History\n\n- 2026-11-06 · 12 minutes"
  assert.equal(changes(journal), "**Result:** ✅ done\n\nWhat changed: a tab.")
  assert.equal(changes("**Pull request** : https://x\n\nUn onglet.\n\n### Historique\n\n- ligne"), "Un onglet.")
})
