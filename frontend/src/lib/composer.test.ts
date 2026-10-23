/* The message bar's decisions, held to what they say.
 *
 *     npm test          (node --test, nothing to install)
 *
 * Node runs this file as it is: it strips the types and imports `composer.ts`
 * directly, which is why that module imports nothing of its own.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import {
  canSend,
  completed,
  completions,
  inserted,
  isCommand,
  kindOf,
  nameFor,
  pastedFiles,
  screen,
  stopsOnEscape,
  settled,
  withAdded,
  without,
  type Pending,
} from "./composer.ts"

const MB = 1024 * 1024
const image = (key: string, state: Pending["state"] = "done"): Pending => ({
  key,
  name: `${key}.png`,
  kind: "image",
  size: 1000,
  state,
})

test("an image, a video and a document are taken; anything else is refused", () => {
  assert.equal(kindOf({ name: "photo.JPG", type: "" }), "image")
  assert.equal(kindOf({ name: "clip.mov", type: "" }), "video")
  assert.equal(kindOf({ name: "spec.pdf", type: "" }), "document")
  assert.equal(kindOf({ name: "sheet.xlsx", type: "" }), "document")
  assert.equal(kindOf({ name: "page.html", type: "text/html" }), null)
  assert.equal(kindOf({ name: "logo.svg", type: "image/svg+xml" }), null, "an SVG is a page")
  const { taken, refused } = screen(
    [
      { name: "a.png", type: "image/png", size: 10 },
      { name: "b.exe", type: "", size: 10 },
      { name: "c.mp4", type: "video/mp4", size: 26 * MB },
    ],
    25
  )
  assert.deepEqual(taken.map((file) => file.name), ["a.png"])
  assert.deepEqual(refused, [
    { name: "b.exe", why: "type" },
    { name: "c.mp4", why: "size" },
  ])
})

test("an image is added, and removed by its cross", () => {
  let list: Pending[] = []
  list = withAdded(list, [image("one", "uploading")])
  assert.equal(list.length, 1)
  assert.equal(canSend({ text: "", attachments: list, busy: false }), false, "still uploading")
  list = settled(list, "one", { state: "done", id: "abcdef123456" })
  assert.equal(list[0].id, "abcdef123456")
  assert.equal(canSend({ text: "", attachments: list, busy: false }), true, "an image alone is a message")
  list = withAdded(list, [image("two")])
  list = without(list, "one")
  assert.deepEqual(list.map((item) => item.key), ["two"])
  list = without(list, "two")
  assert.equal(canSend({ text: "", attachments: list, busy: false }), false)
})

test("a pasted screenshot is taken, and named after the moment it was pasted", () => {
  const screenshot = { name: "image.png", type: "image/png", size: 2048 }
  const files = pastedFiles({ files: [screenshot] })
  assert.equal(files.length, 1)
  assert.deepEqual(screen(files, 25).taken, [screenshot])
  const at = new Date(2026, 8, 30, 9, 5, 7)
  assert.equal(nameFor(screenshot, true, at), "screenshot-090507.png")
  assert.equal(nameFor({ name: "", type: "image/jpeg" }, true, at), "screenshot-090507.jpg")
  assert.equal(nameFor({ name: "report.pdf", type: "application/pdf" }), "report.pdf")
  assert.deepEqual(pastedFiles({ files: [] }), [], "a paste of text carries no file")
  assert.deepEqual(pastedFiles(null), [])
})

test("the arrow is off while there is nothing to send, or an answer is being written", () => {
  assert.equal(canSend({ text: "", attachments: [], busy: false }), false)
  assert.equal(canSend({ text: "   \n ", attachments: [], busy: false }), false)
  assert.equal(canSend({ text: "hello", attachments: [], busy: false }), true)
  assert.equal(canSend({ text: "hello", attachments: [], busy: true }), true, "it waits its turn")
  assert.equal(canSend({ text: ">status", attachments: [], busy: true }), false, "a command runs at once")
  assert.equal(canSend({ text: "hello", attachments: [], busy: false, sending: true }), false)
  assert.equal(
    canSend({ text: "", attachments: [image("x", "error")], busy: false }),
    false,
    "a refused file is not a message"
  )
})

test("a line that starts with > is a command, completed from the ones the runner offers", () => {
  const commands = ["doctor", "list", "logs", "status", "sync"]
  assert.equal(isCommand("  >status"), true)
  assert.equal(isCommand("what is > than"), false)
  assert.deepEqual(completions(">", commands), commands)
  assert.deepEqual(completions(">s", commands), ["status", "sync"])
  assert.deepEqual(completions("> l", commands), ["list", "logs"])
  assert.deepEqual(completions(">status", commands), [], "typed out in full")
  assert.deepEqual(completions(">logs 3ca4", commands), [], "past the verb, nothing to offer")
  assert.deepEqual(completions("status", commands), [], "a sentence is not completed")
  assert.equal(completed("status"), ">status ")
  assert.equal(canSend({ text: ">", attachments: [], busy: false }), false, "no verb yet")
  assert.equal(canSend({ text: ">status", attachments: [], busy: false }), true)
})

test("a transcription lands after what is already typed", () => {
  assert.equal(inserted("", " bonjour "), "bonjour")
  assert.equal(inserted("Regarde ça :", "le bouton est cassé"), "Regarde ça : le bouton est cassé")
  assert.equal(inserted("déjà là", "   "), "déjà là")
})

test("Escape stops a turn only from an empty bar, and only where Stop is offered", () => {
  const empty = { text: "", attachments: [], busy: true, stoppable: true }
  assert.equal(stopsOnEscape(empty), true)
  assert.equal(stopsOnEscape({ ...empty, text: "next question" }), false)
  assert.equal(stopsOnEscape({ ...empty, text: "   " }), true)
  assert.equal(stopsOnEscape({ ...empty, attachments: [image("a.png")] }), false)
  assert.equal(stopsOnEscape({ ...empty, busy: false }), false)
  assert.equal(stopsOnEscape({ ...empty, stoppable: false }), false)
})
