/* The settings page's search, and where a field's help is cut.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { folded, search, splitHelp } from "./settings-search.ts"

test("the line under a label is the first sentence, the rest goes behind the « ? »", () => {
  assert.deepEqual(
    splitHelp("Past it, the session is stopped. Running tickets finish."),
    ["Past it, the session is stopped.", "Running tickets finish."]
  )
  assert.deepEqual(splitHelp("One sentence only."), ["One sentence only.", ""])
  // An abbreviation, a URL and a code span are not ends of sentences.
  assert.deepEqual(
    splitHelp("Where your git repositories are, e.g. `~/workspace`. A project's repository is looked for here."),
    ["Where your git repositories are, e.g. `~/workspace`.", "A project's repository is looked for here."]
  )
  assert.equal(splitHelp("From github.com/settings/tokens. Paste it.")[0], "From github.com/settings/tokens.")
  assert.equal(splitHelp("Rien : « Tout » attend.")[0], "Rien : « Tout » attend.")
  assert.equal(splitHelp("Le niveau. « Lecture seule » protège.")[0], "Le niveau.")
})

test("a search reads past accents and case", () => {
  assert.equal(folded("Jeton d'intégration"), "jeton d'integration")
})

const fields = [
  { name: "web.token", words: ["Jeton de la console", "Le secret qui ouvre la console.", "Console token"] },
  { name: "runner.model", words: ["Modèle par défaut", "`opus`, `sonnet` ou `haiku`.", "Default model"] },
  { name: "runner.resolve_model", words: ["Modèle qui résout les conflits", "Vide : le modèle du ticket."] },
  { name: "notify.telegram.token", words: ["Jeton du bot Telegram", "Depuis @BotFather."] },
]

test("a field is found by its label, its help or its key, the key first", () => {
  assert.deepEqual(search(fields, "jeton").map((field) => field.name), ["web.token", "notify.telegram.token"])
  assert.deepEqual(search(fields, "WEB.TOKEN").map((field) => field.name), ["web.token"])
  assert.deepEqual(search(fields, "modele").map((field) => field.name), ["runner.model", "runner.resolve_model"])
  // The help counts, after the labels.
  assert.deepEqual(search(fields, "botfather").map((field) => field.name), ["notify.telegram.token"])
  // In English too, on a console in French.
  assert.deepEqual(search(fields, "default model").map((field) => field.name), ["runner.model"])
  // A key is a better answer than a label that happens to hold the word.
  assert.equal(search(fields, "resolve")[0].name, "runner.resolve_model")
})

test("one letter finds nothing, and the list stops", () => {
  assert.deepEqual(search(fields, "e"), [])
  assert.equal(search(fields, "to", 2).length, 2)
})
