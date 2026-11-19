/* The console's built stylesheet asks `:has()` nothing Chrome cannot narrow.
 *
 *     npm test          (node --test, nothing to install)
 *
 * A `:has()` written before the element a rule styles — `.x:has(…) > [a]`,
 * `:is(.group:has(…) *)`, which `group-has-*` and `has-[…]:*:` compile to —
 * left Chrome unable to tell which elements a change under it may now match:
 * each element inserted under `<body>`, as a window's portal is, restyled every
 * element of the page when the subject was anything, every element with a
 * `data-slot` or a `role` when it was one of those. A window took 1 s to open
 * over the table of 2,000 tickets. With a class or a tag as the subject, it
 * restyles those elements only; `index.css` says how the others are written.
 *
 * What is read is the sheet `npm run build` wrote into `web/static`, the one
 * the console serves — with whatever Tailwind found in the packages' files.
 */
import assert from "node:assert/strict"
import { readFileSync, readdirSync } from "node:fs"
import { test } from "node:test"

const ASSETS = new URL("../../../src/ponos/web/static/assets/", import.meta.url)

/** A selector list cut at its own commas. */
function items(list: string): string[] {
  const out: string[] = []
  let start = 0
  for (let at = groupEnd(list, 0); at < list.length; at = groupEnd(list, at + 1)) {
    out.push(list.slice(start, at).trim())
    start = at + 1
  }
  out.push(list.slice(start).trim())
  return out
}

/** A rule nested in another, written out whole: `&` is the parent, or the parent comes first. */
function nested(parent: string | undefined, child: string): string {
  if (!parent) return child
  return items(parent)
    .flatMap((outer) => items(child).map((inner) => (inner.includes("&") ? inner.replaceAll("&", outer) : `${outer} ${inner}`)))
    .join(",")
}

/** Every selector of a sheet — in an at-rule's block, or nested in another rule — as the browser reads it. */
function selectors(css: string): string[] {
  const found: string[] = []
  // What each open block is: the selector of a rule, or nothing for an at-rule.
  const open: (string | undefined)[] = []
  let start = 0
  let quote = ""
  for (let at = 0; at < css.length; at++) {
    const char = css[at]
    if (quote) {
      if (char === "\\") at++
      else if (char === quote) quote = ""
    } else if (char === "\\") at++
    else if (char === '"' || char === "'") quote = char
    else if (char === "{") {
      const prelude = css.slice(start, at).trim()
      const parent = open.findLast((selector) => selector !== undefined)
      if (prelude.startsWith("@")) open.push(undefined)
      else {
        const whole = nested(parent, prelude)
        found.push(whole)
        open.push(whole)
      }
      start = at + 1
    } else if (char === "}") {
      open.pop()
      start = at + 1
    } else if (char === ";") start = at + 1
  }
  return found
}

/** Where the group that opens before `from` closes — at a comma too, with `list` — or the end of the text. */
function groupEnd(text: string, from: number, list = true): number {
  let depth = 0
  for (let at = from; at < text.length; at++) {
    const char = text[at]
    if (char === "\\") at++
    else if (char === "(") depth++
    else if (char === ")") {
      if (depth === 0) return at
      depth--
    } else if (list && char === "," && depth === 0) return at
  }
  return text.length
}

/** The text with every parenthesised group and attribute emptied: what is left is its own level. */
function ownLevel(text: string): string {
  let out = ""
  let depth = 0
  for (let at = 0; at < text.length; at++) {
    const char = text[at]
    if (char === "\\") {
      if (depth === 0) out += text.slice(at, at + 2)
      at++
    } else if (char === "(" || char === "[") {
      if (depth === 0) out += char
      depth++
    } else if (char === ")" || char === "]") {
      depth--
      if (depth === 0) out += char
    } else if (depth === 0) out += char
  }
  return out
}

/** Each `:has()` of a selector that is not on the element the rule styles, with that element. */
function before(selector: string): { has: string; subject: string }[] {
  const wrong: { has: string; subject: string }[] = []
  for (let at = selector.indexOf(":has("); at >= 0; at = selector.indexOf(":has(", at + 1)) {
    const close = groupEnd(selector, at + 5, false)
    // What follows the `:has()` in its own group: the rest of the selector, or
    // of the `:is()` / `:not()` it is written in.
    const rest = ownLevel(selector.slice(close + 1, groupEnd(selector, close + 1)))
    const combinator = rest.search(/[\s>+~]/)
    if (combinator < 0) continue
    const subject = rest.slice(combinator).trim().split(/[\s>+~]+/).pop() ?? ""
    // A class or a tag narrows it down; `*`, an attribute or a pseudo-class alone do not.
    if (/^[a-z][a-z0-9-]*|\.(?:[^\s\\]|\\.)/i.test(subject)) continue
    wrong.push({ has: selector.slice(at, close + 1), subject: subject || "*" })
  }
  return wrong
}

test("the check finds what Tailwind compiles group-has and has-*: to, and lets the rest by", () => {
  assert.equal(before(".a:is(:where(.group\\/field):has(:disabled) *)").length, 1)
  assert.equal(before(":is(.b:has(>[data-variant=outline])>*)[data-slot=input-group]").length, 1)
  assert.equal(before(".c:has(>[data-variant=outline])>[data-slot=select-trigger]:focus-visible").length, 1)
  assert.equal(before("div:has(>[data-projects-aside])>:not([data-projects-aside])").length, 1)
  assert.equal(before(":is(.d:has(>[data-slot=field-content])>[role=checkbox],.d:has(>[data-slot=field-content]) [role=radio])").length, 2)
  // On the element itself, or before a class or a tag.
  assert.equal(before(".has-\\[\\>svg\\]\\:px-4:has(>svg)").length, 0)
  assert.equal(before("[data-slot]:not(:has(~[data-slot]))").length, 0)
  assert.equal(before("[data-slot=input-group]:is(.e>*):is([data-variant=outline],[data-variant=outline]~*,:has(~[data-variant=outline]))").length, 0)
  assert.equal(before(":where(.group\\/item):has([data-slot=item-description]) .f\\:self-start").length, 0)
  assert.equal(before(".milkdown:has(.milkdown-link-edit[data-show=true]) .milkdown-toolbar").length, 0)
  assert.equal(before(".g:has(>[data-variant=outline])>input:focus-visible").length, 0)
  assert.equal(before("body:has(>[data-slot=dialog-overlay],>[data-slot=sheet-overlay])").length, 0)
  // A nested rule is read with its parent.
  assert.deepEqual(selectors("@layer x{body:has([data-slot=head]){color:red;[data-slot=tabs]>[data-slot=card]{display:none}}}"), [
    "body:has([data-slot=head])",
    "body:has([data-slot=head]) [data-slot=tabs]>[data-slot=card]",
  ])
  assert.equal(before("body:has([data-slot=head]) [data-slot=tabs]>[data-slot=card]").length, 1)
  assert.equal(before('body[data-context-page] nav[aria-label="Bread crumb"] li').length, 0)
})

test("no :has() in the built stylesheet sits before a subject Chrome cannot narrow", () => {
  const sheets = readdirSync(ASSETS).filter((name) => name.endsWith(".css"))
  assert.ok(sheets.length > 0, "no stylesheet in web/static/assets: run npm run build")
  const wrong = sheets.flatMap((name) =>
    selectors(readFileSync(new URL(name, ASSETS), "utf8")).flatMap((selector) =>
      before(selector).map(({ has, subject }) => `${name}: ${has} before ${subject} in ${selector}`)
    )
  )
  assert.deepEqual(wrong, [])
})

test("no `~` in the built stylesheet styles a slot that is any slot", () => {
  // `.x > [data-slot] ~ [data-slot]` marks every parent of a slot — `<body>`,
  // whose windows are slots — as styling its children by the ones before them:
  // a window closing over the table of 2,000 tickets restyled the page, 430 ms
  // per rule. `index.css` writes the button group's with `:nth-child(n + 2 of …)`.
  const wrong = readdirSync(ASSETS)
    .filter((name) => name.endsWith(".css"))
    .flatMap((name) =>
      selectors(readFileSync(new URL(name, ASSETS), "utf8"))
        .flatMap(items)
        .filter((selector) => /~\s*\[data-slot\]\s*$/.test(selector))
        .map((selector) => `${name}: ${selector}`)
    )
  assert.deepEqual(wrong, [])
})
