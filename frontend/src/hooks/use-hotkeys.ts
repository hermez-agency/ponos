import * as React from "react"

import { HOTKEYS, ariaLabel, hotkeyFor, isMac, label, type HotkeyId } from "@/lib/hotkeys"

/* Where the shortcuts listed in `hotkeys.ts` are listened for.
 *
 * On the window, in the capture phase: a key pressed in the Markdown editor or
 * in the palette's own field reaches here before anything under it can keep it
 * for itself. A component asks for the shortcuts it answers and nothing else,
 * so two of them can listen at once — the palette for one key, the drawer for
 * the other — without either knowing the other is there. A handler that
 * returns `false` lets the key go on where it was pressed, as if nobody listened.
 */

const MAC = typeof navigator !== "undefined" && isMac(navigator.platform || navigator.userAgent)

/** Run `handlers[id]` when its shortcut is pressed, the browser's own use of the key withheld. */
export function useHotkeys(handlers: Partial<Record<HotkeyId, () => void | false>>) {
  // The latest handlers, so a listener is added once and not at every render.
  const latest = React.useRef(handlers)
  latest.current = handlers

  React.useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.repeat || event.isComposing) return
      const id = hotkeyFor(event, event.target as HTMLElement | null)
      const handler = id ? latest.current[id] : undefined
      if (!handler || handler() === false) return
      event.preventDefault()
    }
    window.addEventListener("keydown", listener, { capture: true })
    return () => window.removeEventListener("keydown", listener, { capture: true })
  }, [])
}

/** How a shortcut reads on this machine, and how it is said to a screen reader. */
export function hotkeyLabel(id: HotkeyId): { label: string; aria: string } {
  return { label: label(HOTKEYS[id], MAC), aria: ariaLabel(HOTKEYS[id], MAC) }
}
