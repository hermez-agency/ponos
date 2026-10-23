/* The console's shortcuts, held to what they say.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { HOTKEYS, ariaLabel, hotkeyFor, isTyping, label, matches } from "./hotkeys.ts"

const press = (key: string, held: Partial<Record<"ctrlKey" | "metaKey" | "altKey" | "shiftKey", boolean>> = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...held,
})

test("Ctrl+K and ⌘K both open the palette, whatever the case of the letter", () => {
  assert.equal(matches(press("k", { ctrlKey: true }), HOTKEYS.palette), true)
  assert.equal(matches(press("k", { metaKey: true }), HOTKEYS.palette), true)
  assert.equal(matches(press("K", { ctrlKey: true }), HOTKEYS.palette), true)
})

test("a bare letter, or one held with Shift or Alt, is not a shortcut", () => {
  assert.equal(matches(press("k"), HOTKEYS.palette), false)
  // Ctrl+Shift+J is the browser's own console.
  assert.equal(matches(press("j", { ctrlKey: true, shiftKey: true }), HOTKEYS.console), false)
  // AltGr arrives as Ctrl+Alt.
  assert.equal(matches(press("k", { ctrlKey: true, altKey: true }), HOTKEYS.palette), false)
})

test("the two shortcuts are two keys", () => {
  assert.equal(hotkeyFor(press("k", { ctrlKey: true }), null), "palette")
  assert.equal(hotkeyFor(press("j", { ctrlKey: true }), null), "console")
  assert.equal(hotkeyFor(press("l", { ctrlKey: true }), null), null)
})

test("/ goes to the search, Shift or not, and is a character in a field", () => {
  assert.equal(hotkeyFor(press("/"), null), "search")
  // Shift+: on a French keyboard.
  assert.equal(hotkeyFor(press("/", { shiftKey: true }), { tagName: "DIV" }), "search")
  assert.equal(hotkeyFor(press("/"), { tagName: "INPUT", type: "search" }), null)
  assert.equal(hotkeyFor(press("/", { ctrlKey: true }), null), null)
  assert.equal(label(HOTKEYS.search, true), "/")
})

test("a field is where words are typed, a button is not", () => {
  assert.equal(isTyping({ tagName: "TEXTAREA" }), true)
  assert.equal(isTyping({ tagName: "INPUT", type: "text" }), true)
  assert.equal(isTyping({ tagName: "INPUT" }), true)
  assert.equal(isTyping({ tagName: "DIV", isContentEditable: true }), true)
  assert.equal(isTyping({ tagName: "INPUT", type: "checkbox" }), false)
  assert.equal(isTyping({ tagName: "BUTTON" }), false)
  assert.equal(isTyping(null), false)
})

test("the palette and the console answer from inside a field", () => {
  const field = { tagName: "TEXTAREA" }
  assert.equal(hotkeyFor(press("k", { metaKey: true }), field), "palette")
  assert.equal(hotkeyFor(press("j", { metaKey: true }), field), "console")
})

test("a shortcut is written the way the machine writes it", () => {
  assert.equal(label(HOTKEYS.palette, true), "⌘K")
  assert.equal(label(HOTKEYS.palette, false), "Ctrl+K")
  assert.equal(ariaLabel(HOTKEYS.console, true), "Meta+J")
  assert.equal(ariaLabel(HOTKEYS.console, false), "Control+J")
})

test("Ctrl+Shift+O starts a new conversation, and only with the Shift", () => {
  assert.equal(hotkeyFor(press("O", { ctrlKey: true, shiftKey: true }), { tagName: "TEXTAREA" }), "newChat")
  assert.equal(hotkeyFor(press("o", { metaKey: true, shiftKey: true }), null), "newChat")
  assert.equal(hotkeyFor(press("o", { ctrlKey: true }), null), null)
  assert.equal(label(HOTKEYS.newChat, false), "Ctrl+Shift+O")
  assert.equal(label(HOTKEYS.newChat, true), "⌘⇧O")
  assert.equal(ariaLabel(HOTKEYS.newChat, false), "Control+Shift+O")
})
