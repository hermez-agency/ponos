/* The console's keyboard shortcuts, all of them, in one list.
 *
 * Four today: the palette (Ctrl+K, ⌘K on a Mac), the drawer the conversation
 * lives in (Ctrl+J, ⌘J), a new conversation in it (Ctrl+Shift+O, ⌘⇧O), and the search over the board (/, the key most sites
 * give their search field). One more is a line here and a handler where it acts —
 * `useHotkeys` reads this list, the palette prints it, the bubble's tooltip
 * says it — so a shortcut is never written in one place and forgotten in
 * another.
 *
 * Both are keys the browser has a use for — the search bar, the downloads —
 * and both are among the ones a page may take back, which Ctrl+T or Ctrl+W
 * are not. Ctrl+J rather than Ctrl+` because a backquote is AltGr+7 on a
 * French keyboard, which is most of the keyboards this console is typed on.
 *
 * Plain data in, plain data out, and nothing imported: `node --test` reads this
 * file as it stands, the way it reads `composer.ts`.
 */

export type HotkeyId = "palette" | "console" | "newChat" | "search"

export interface Hotkey {
  id: HotkeyId
  /** `KeyboardEvent.key`, lower case: the letter printed on the key, whatever the layout. */
  key: string
  /** Held with Ctrl, or ⌘ on a Mac. */
  mod: boolean
  /** Held with Shift too. Only a shortcut with `mod` asks for it: without Ctrl,
   * Shift comes with the character (see `matches`). */
  shift?: boolean
  /** Still a shortcut while the cursor is in a field. A bare letter is not:
   * typed in a field, it is a letter. */
  inFields: boolean
}

export const HOTKEYS: Record<HotkeyId, Hotkey> = {
  palette: { id: "palette", key: "k", mod: true, inFields: true },
  console: { id: "console", key: "j", mod: true, inFields: true },
  newChat: { id: "newChat", key: "o", mod: true, shift: true, inFields: true },
  search: { id: "search", key: "/", mod: false, inFields: false },
}

/** What `matches` reads of a keydown. */
export interface KeyPress {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  altKey: boolean
  shiftKey: boolean
}

/* Ctrl or ⌘, whichever the machine has: a Mac with Ctrl pressed is not wrong
 * about what it meant. Never with Alt, nor Shift with Ctrl unless the shortcut
 * says so — Ctrl+Shift+J is the browser's own console, and AltGr arrives as Ctrl+Alt on Windows. A key
 * alone may come with Shift: "/" is Shift+: on a French keyboard, and
 * `key` already says the character it made. */
export function matches(press: KeyPress, hotkey: Hotkey): boolean {
  const mod = press.ctrlKey || press.metaKey
  if (mod !== hotkey.mod || press.altKey || (hotkey.mod && press.shiftKey !== !!hotkey.shift)) return false
  return press.key.toLowerCase() === hotkey.key
}

/** What `isTyping` reads of the element a key was pressed in. */
export interface Target {
  tagName?: string
  isContentEditable?: boolean
  type?: string
}

/* Buttons are inputs too, to the DOM: a checkbox with the focus is not
 * somebody typing. */
const NOT_TYPED = new Set(["button", "checkbox", "radio", "submit", "reset", "range", "color", "file"])

/** Whether a key pressed there is a word being typed. */
export function isTyping(target: Target | null | undefined): boolean {
  if (!target) return false
  if (target.isContentEditable) return true
  const tag = (target.tagName ?? "").toLowerCase()
  if (tag === "textarea" || tag === "select") return true
  return tag === "input" && !NOT_TYPED.has((target.type ?? "text").toLowerCase())
}

/** The shortcut a keydown asks for, if any, and if it may be asked from there. */
export function hotkeyFor(press: KeyPress, target: Target | null | undefined): HotkeyId | null {
  const typing = isTyping(target)
  for (const hotkey of Object.values(HOTKEYS)) {
    if (typing && !hotkey.inFields) continue
    if (matches(press, hotkey)) return hotkey.id
  }
  return null
}

/** Whether the machine is a Mac, from `navigator.platform` or the user agent. */
export const isMac = (platform: string): boolean => /mac|iphone|ipad/i.test(platform)

/** How the shortcut is written for whoever reads it: `⌘K` on a Mac, `Ctrl+K` elsewhere. */
export function label(hotkey: Hotkey, mac: boolean): string {
  const key = hotkey.key.toUpperCase()
  if (!hotkey.mod) return key
  return `${mac ? "⌘" : "Ctrl+"}${hotkey.shift ? (mac ? "⇧" : "Shift+") : ""}${key}`
}

/** The same, as `aria-keyshortcuts` wants it said. */
export function ariaLabel(hotkey: Hotkey, mac: boolean): string {
  const key = hotkey.key.toUpperCase()
  return hotkey.mod ? `${mac ? "Meta" : "Control"}+${hotkey.shift ? "Shift+" : ""}${key}` : key
}
