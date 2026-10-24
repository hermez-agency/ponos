/* The copy buttons, held to a console served without `navigator.clipboard`.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { toClipboard, type Place } from "./clipboard.ts"

/** A page with a body, whose `execCommand("copy")` answers `copies` and keeps what was selected. */
function page(copies: boolean) {
  const seen: { copied: string | null; left: number; focused: boolean } = { copied: null, left: 0, focused: false }
  const children: unknown[] = []
  let selected = ""
  const previous = { focus: () => (seen.focused = true) }
  const document = {
    activeElement: previous,
    body: {
      appendChild: (child: unknown) => children.push(child),
      removeChild: (child: unknown) => children.splice(children.indexOf(child), 1),
    },
    createElement: () => {
      const area = {
        value: "",
        style: {} as Record<string, string>,
        setAttribute: () => {},
        select: () => (selected = area.value),
      }
      return area
    },
    execCommand: (command: string) => {
      if (command !== "copy" || !copies) return false
      seen.copied = selected
      return true
    },
  }
  return { document, seen, children }
}

test("without navigator.clipboard, the text is copied by the page itself", async () => {
  const { document, seen, children } = page(true)
  const place = { navigator: {}, document } as unknown as Place
  assert.equal(await toClipboard("ponos mcp", place), true)
  assert.equal(seen.copied, "ponos mcp")
  assert.equal(children.length, 0, "the field it copied from is gone")
  assert.equal(seen.focused, true, "the focus is back where it was")
})

test("without navigator.clipboard, and a page that refuses too, it says so", async () => {
  const { document } = page(false)
  assert.equal(await toClipboard("ponos mcp", { navigator: {}, document } as unknown as Place), false)
  assert.equal(await toClipboard("ponos mcp", {} as Place), false)
})

test("navigator.clipboard is asked first", async () => {
  const written: string[] = []
  const { document, seen } = page(true)
  const navigator = { clipboard: { writeText: async (text: string) => void written.push(text) } }
  assert.equal(await toClipboard("abc", { navigator, document } as unknown as Place), true)
  assert.deepEqual(written, ["abc"])
  assert.equal(seen.copied, null)
})

test("a clipboard that refuses (no permission) falls back on the page", async () => {
  const { document, seen } = page(true)
  const navigator = { clipboard: { writeText: () => Promise.reject(new Error("NotAllowedError")) } }
  assert.equal(await toClipboard("abc", { navigator, document } as unknown as Place), true)
  assert.equal(seen.copied, "abc")
})
