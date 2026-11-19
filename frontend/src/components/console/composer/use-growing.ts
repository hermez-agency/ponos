import * as React from "react"

/* The field grows with what is written, up to a point — without stopping a keystroke to measure it.
 *
 * It used to be measured on every keystroke: its height set to `auto`, then
 * its `scrollHeight` read. That read forces the page's style and layout, the
 * conversation's included, inside the keystroke's own handler: tens of
 * milliseconds a keystroke at a hundred messages, where React's render took
 * one or two.
 *
 * `field-sizing: content` (on the field, in `field.tsx`) has the browser size
 * the field to its words itself, within its `min-h` and `max-h`, and nothing
 * here runs. Where it is not understood the field is still measured, but never
 * collapsed to `auto` on a keystroke that can only make it longer: a field
 * with a height of its own reports in `scrollHeight` whatever overflows it, so
 * growing needs no reset, and a field already as tall as it goes is not read
 * at all. Shrinking does need one, and is looked for only when there are fewer
 * words in a field more than one line tall; emptied, it is one line again
 * without a measure.
 */

/** About eight lines of the field, past which it scrolls instead of growing. */
const TALLEST = 200

/** Whether the browser sizes the field itself; asked once, the answer never changes. */
export const SIZES_ITSELF =
  typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("field-sizing", "content")

const lines = (text: string) => text.split("\n").length

export function useGrowing(field: React.RefObject<HTMLTextAreaElement | null>, text: string, recording: boolean) {
  const measured = React.useRef<{ element: HTMLTextAreaElement | null; text: string }>({ element: null, text: "" })

  React.useLayoutEffect(() => {
    if (SIZES_ITSELF) return
    const element = field.current
    const before = measured.current
    measured.current = { element, text }
    if (!element) return
    const style = element.style

    // Empty, it is one line again: its `rows`, with no height to measure.
    if (!text) {
      style.height = ""
      return
    }

    // A field drawn again (after the dictation, say) has lost its height.
    const fresh = element !== before.element
    const fewer = text.length < before.text.length || lines(text) < lines(before.text)
    if (fresh || (fewer && style.height)) {
      style.height = "auto"
      const height = element.scrollHeight
      // Back to one line, it keeps no height, and the next deletion is not measured.
      style.height = height > element.clientHeight ? `${Math.min(height, TALLEST)}px` : ""
      return
    }

    // More words, in a field not yet as tall as it goes: what overflows says how much to grow.
    if (fewer || element.clientHeight >= TALLEST) return
    const height = element.scrollHeight
    if (height > element.clientHeight) style.height = `${Math.min(height, TALLEST)}px`
  }, [field, text, recording])
}
