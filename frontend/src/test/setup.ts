import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

/* What jsdom leaves out and the console's components reach for.
 *
 * The console is read in English here, whatever this machine's zone or
 * language says (`lib/i18n.ts` would pick French on a machine in Paris): a
 * test asks for the sentence in the source, which is the key, so a French
 * dictionary that changed one word moves no test. Set before any test file
 * imports `i18n.ts`, which reads it once, on import.
 */
localStorage.setItem("ponos-language", "en")

// Radix measures what it lays out, and asks the pointer where it is.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Element.prototype.scrollIntoView ??= () => {}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList

// The bar previews an image it was given by an object URL.
URL.createObjectURL ??= () => "blob:preview"
URL.revokeObjectURL ??= () => {}

afterEach(() => {
  cleanup()
  localStorage.clear()
  localStorage.setItem("ponos-language", "en")
})
